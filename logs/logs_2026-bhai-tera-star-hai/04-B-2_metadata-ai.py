#!/usr/bin/env python3
"""
04-B-2_metadata-ai.py
AI Fallback: Uses Gemini 3.5/3.1 Flash-Lite to extract missing critic names 
and star ratings from raw HTML chunks if JSON-LD parsing failed.
"""

import builtins
import json
import os
import glob
import time
import re
from datetime import datetime
from google import genai
from google.genai import errors

# ---------------------------------------------------------------------------
# Global Print Override for Real-Time CI/CD Streaming
# ---------------------------------------------------------------------------
def print(*args, **kwargs):
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

# ---------------------------------------------------------------------------
# Setup & Absolute Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "prompt_missing_metadata.txt")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("[ERROR] GEMINI_API_KEY environment variable not found!")
    exit(1)

client = genai.Client(api_key=API_KEY)

# Using Flash Lite exclusively to utilize the high RPD limits
MODEL_CONFIG = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

# -----------------------------------------------------------------------------
# 7-Column Pipeline Metric Tracker
# -----------------------------------------------------------------------------
class PipelineTracker:
    def __init__(self, metric_name, earlier_completed, earlier_pending):
        self.metric_name = metric_name
        self.earlier_completed = earlier_completed
        self.earlier_pending = earlier_pending
        self.processed = 0
        self.succeeded = 0
        self.failed = 0

    def add_success(self, count=1):
        self.processed += count
        self.succeeded += count

    def add_failure(self, count=1):
        self.processed += count
        self.failed += count

    def print_summary(self):
        new_completed = self.earlier_completed + self.succeeded
        new_pending = self.earlier_pending - self.succeeded

        print("\n" + "=" * 125)
        print(f" PIPELINE METRIC: {self.metric_name}")
        print("=" * 125)
        print(f"| {'Earlier Completed':^17} | {'Earlier Pending':^15} | {'Processed':^9} | {'Success':^7} | {'Failure':^7} | {'New Completed':^13} | {'New Pending':^11} |")
        print("-" * 125)
        print(f"| {self.earlier_completed:^17} | {self.earlier_pending:^15} | {self.processed:^9} | {self.succeeded:^7} | {self.failed:^7} | {new_completed:^13} | {new_pending:^11} |")
        print("=" * 125 + "\n")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean_html(html_content):
    """
    Strips out massive base64 image strings to save tokens, 
    but preserves the raw HTML/DOM completely intact.
    """
    return re.sub(r'data:image\/[^;]+;base64,[^"\'\s]+', '', html_content)

def is_downloaded_successfully(pub):
    val = pub.get("webpage_extraction_successful", pub.get("is_downloaded"))
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().upper() in ["Y", "YES", "TRUE", "SUCCESS"]
    return False

def needs_extraction(pub):
    """Determines if a publisher needs Gemini fallback extraction and is eligible."""
    url = pub.get("review_url", "")
    if not url or url.strip().upper() == "NA" or not is_downloaded_successfully(pub):
        return False

    # Circuit Breaker: Do not attempt if we've already tried 5 or more times
    attempts = pub.get("ai_extraction_attempt_count", 0)
    if attempts >= 5:
        return False

    bad_values = ["na", "could not find from jsonld", "none", "null", ""]
    critic = str(pub.get("critic_name", "")).strip().lower()
    rating = str(pub.get("star_rating", "")).strip().lower()

    # If both fields are already populated and valid, skip
    if critic not in bad_values and rating not in bad_values:
        return False

    return True

def extract_metadata_with_gemini(movie_name, html_text, prompt_template):
    prompt = prompt_template.replace("{movie_name}", str(movie_name)).replace("{webpage_text}", str(html_text))

    for model_name in MODEL_CONFIG:
        print(f"      [Attempting Model: {model_name}]")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )

            if response and response.text:
                raw_json = response.text.strip()
                if raw_json.startswith("```json"):
                    raw_json = raw_json[7:]
                elif raw_json.startswith("```"):
                    raw_json = raw_json[3:]
                if raw_json.endswith("```"):
                    raw_json = raw_json[:-3]

                raw_json = raw_json.strip()

                if not raw_json.startswith("{"):
                    raw_json = "{" + raw_json

                return json.loads(raw_json), model_name

        except errors.APIError as e:
            print(f"      [API Error on {model_name}]: {e}")
        except json.JSONDecodeError as e:
            print(f"      [JSON Parse Error on {model_name}]: {e}")
        except Exception as e:
            print(f"      [Unexpected Error on {model_name}]: {e}")
            
        print("      [Fallback] Trying next model...")

    return None, None

def get_live_movie_slugs():
    slugs = []
    live_master_file = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")

    if os.path.exists(live_master_file):
        with open(live_master_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            movie_list = data if isinstance(data, list) else data.get("movies", [])
            for movie in movie_list:
                if isinstance(movie, dict) and "slug" in movie:
                    slugs.append(movie["slug"])
    else:
        for file_path in glob.glob(os.path.join(BASE_DIR, "data", "movies", "*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    slug = data.get("slug") or data.get("movie", {}).get("slug")
                    if slug:
                        slugs.append(slug)
                except Exception:
                    pass
    return list(set(slugs))

# ---------------------------------------------------------------------------
# Main Logic
# ---------------------------------------------------------------------------
def process_movie_file(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" CHECKING MISSING METADATA: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_name = data.get("movie", {}).get("name")
    movie_slug = data.get("movie", {}).get("slug")
    publishers = data.get("publishers", [])

    # HTML Directory Hunting
    possible_html_dirs = [
        os.path.join(BASE_DIR, f"data/webpages/html_{movie_slug}"),
        os.path.join(BASE_DIR, f"data/webpages/{movie_slug}"),
        os.path.join(BASE_DIR, "data/webpages")
    ]
    html_dir = next((d for d in possible_html_dirs if os.path.exists(d)), None)

    # Logging Setup
    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "04-B-2_metadata-ai.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    bad_values = ["na", "could not find from jsonld", "none", "null", ""]
    
    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        if is_downloaded_successfully(pub) and pub.get("review_url") not in [None, "NA", ""]:
            if needs_extraction(pub):
                earlier_pending += 1
            else:
                earlier_completed += 1

    tracker = PipelineTracker("AI Metadata Extraction (Gemini)", earlier_completed, earlier_pending)

    movie_log_entry = {
        "earlier_completed": earlier_completed,
        "earlier_pending": earlier_pending,
        "processed": 0,
        "success": 0,
        "failure": 0,
        "new_completed": 0,
        "new_pending": 0,
        "publisher_details": {}
    }

    if not html_dir:
        print(f"[WARNING] HTML directory not found. Cannot perform AI extraction.")
        return

    updated_count = 0

    for pub in publishers:
        if needs_extraction(pub):
            pub_id = pub.get("publisher_id", "unknown")
            current_attempts = pub.get("ai_extraction_attempt_count", 0)

            print(f"\n  [*] Processing [{pub_id}] - Attempt {current_attempts + 1}/5")
            pub["ai_extraction_attempt_count"] = current_attempts + 1
            movie_log_entry["processed"] += 1

            html_path = os.path.join(html_dir, f"webpage_{pub_id}_{movie_slug}.html")
            if not os.path.exists(html_path):
                alt_path = os.path.join(html_dir, f"webpage_{pub_id}.html")
                if os.path.exists(alt_path):
                    html_path = alt_path
                else:
                    print(f"      [SKIP] HTML file not found.")
                    movie_log_entry["publisher_details"][pub_id] = {"status": "SKIPPED", "reason": "HTML file missing"}
                    continue

            with open(html_path, "r", encoding="utf-8") as hf:
                raw_html = hf.read()

            cleaned_html = clean_html(raw_html)
            chunk_size = 800000
            chunks = [cleaned_html[i:i+chunk_size] for i in range(0, len(cleaned_html), chunk_size)]
            print(f"      [HTML size: {len(cleaned_html)} chars -> Split into {len(chunks)} chunk(s)]")

            current_critic = str(pub.get("critic_name", "NA"))
            current_rating = str(pub.get("star_rating", "NA"))
            found_new_data = False
            used_model = "None"

            for idx, chunk in enumerate(chunks):
                missing_critic = current_critic.strip().lower() in bad_values
                missing_rating = current_rating.strip().lower() in bad_values

                print(f"      [Analyzing Chunk {idx + 1}/{len(chunks)}...]")

                extracted_data, model_success = extract_metadata_with_gemini(movie_name, chunk, prompt_template)

                if extracted_data:
                    used_model = model_success
                    new_critic = str(extracted_data.get("critic_name", "NA"))
                    new_rating = str(extracted_data.get("star_rating", "NA"))

                    if missing_critic and new_critic.strip().lower() not in bad_values:
                        current_critic = new_critic
                        pub["critic_name"] = current_critic
                        print(f"      => Extracted Critic: {current_critic}")
                        found_new_data = True

                    if missing_rating and new_rating.strip().lower() not in bad_values:
                        current_rating = new_rating
                        pub["star_rating"] = current_rating
                        print(f"      => Extracted Rating: {current_rating}")
                        found_new_data = True

                print("      [Waiting 65 seconds to respect 1 RPM limit...]")
                time.sleep(65)

                missing_critic = current_critic.strip().lower() in bad_values
                missing_rating = current_rating.strip().lower() in bad_values

                if not missing_critic and not missing_rating:
                    print("      [Found both fields. Halting chunk processing for this publisher.]")
                    break

            if not missing_critic and not missing_rating:
                pub["ai_extraction_status"] = "found both"
                tracker.add_success()
                movie_log_entry["success"] += 1
            elif not missing_critic or not missing_rating:
                pub["ai_extraction_status"] = "found one"
                tracker.add_success()  # Partial success still counts as moving forward
                movie_log_entry["success"] += 1
            else:
                pub["ai_extraction_status"] = "found none"
                tracker.add_failure()
                movie_log_entry["failure"] += 1

            print(f"      [Final Status]: {pub['ai_extraction_status'].upper()}")

            if found_new_data:
                current_ld_status = pub.get("json_ld_extraction_status", "")
                if "Augmented by Gemini" not in current_ld_status:
                    pub["json_ld_extraction_status"] = f"{current_ld_status} | Augmented by Gemini"
                updated_count += 1
                
            movie_log_entry["publisher_details"][pub_id] = {
                "status": pub["ai_extraction_status"],
                "model": used_model,
                "critic_name": pub["critic_name"],
                "star_rating": pub["star_rating"]
            }

            # Iterative Save
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

    movie_log_entry["new_completed"] = earlier_completed + movie_log_entry["success"]
    movie_log_entry["new_pending"] = earlier_pending - movie_log_entry["success"]

    script_log_data = {}
    if os.path.exists(script_log_path) and os.path.getsize(script_log_path) > 0:
        try:
            with open(script_log_path, "r", encoding="utf-8") as lf:
                script_log_data = json.load(lf)
        except json.JSONDecodeError:
            pass

    script_log_data[datetime.now().astimezone().isoformat()] = movie_log_entry

    try:
        with open(script_log_path, "w", encoding="utf-8") as lf:
            json.dump(script_log_data, lf, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[ERROR] Could not write to log file: {e}")

    tracker.print_summary()

def main():
    if not os.path.exists(PROMPT_FILE):
        print(f"[FATAL] Prompt file '{PROMPT_FILE}' not found!")
        return

    with open(PROMPT_FILE, "r", encoding="utf-8") as pf:
        prompt_template = pf.read()

    live_slugs = get_live_movie_slugs()
    target_files = [os.path.join(BASE_DIR, "data", "reviews", f"reviews_{slug}.json") for slug in live_slugs if os.path.exists(os.path.join(BASE_DIR, "data", "reviews", f"reviews_{slug}.json"))]

    if not target_files:
        print("[ERROR] No JSON files found for live movies.")
        return

    for json_path in target_files:
        process_movie_file(json_path, prompt_template)

if __name__ == "__main__":
    main()
