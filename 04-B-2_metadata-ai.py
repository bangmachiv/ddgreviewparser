#!/usr/bin/env python3
"""
04-B-2_metadata-ai.py
AI Fallback: Reads gaps from `jsonld_` fields. 
Strictly writes discovered metadata to `ai_critic_name` and `ai_star_rating`.
Prints explicit, structured step-by-step logs.
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
MODEL_CONFIG = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

# -----------------------------------------------------------------------------
# Pipeline Metric Tracker
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
    """Strips massive base64 images to save tokens, keeps HTML/DOM intact."""
    return re.sub(r'data:image\/[^;]+;base64,[^"\'\s]+', '', html_content)

def is_downloaded_successfully(pub):
    val = pub.get("webpage_extraction_successful", pub.get("is_downloaded"))
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().upper() in ["Y", "YES", "TRUE", "SUCCESS"]
    return False

def extract_metadata_with_gemini(movie_name, html_text, prompt_template):
    prompt = prompt_template.replace("{movie_name}", str(movie_name)).replace("{webpage_text}", str(html_text))

    for model_name in MODEL_CONFIG:
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

        except Exception:
            pass

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

    possible_html_dirs = [
        os.path.join(BASE_DIR, f"data/webpages/html_{movie_slug}"),
        os.path.join(BASE_DIR, f"data/webpages/{movie_slug}"),
        os.path.join(BASE_DIR, "data/webpages")
    ]
    html_dir = next((d for d in possible_html_dirs if os.path.exists(d)), None)

    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "04-B-2_metadata-ai.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    # Core skip flags. "failed" handles the string written by 04-B-1.
    bad_values = ["na", "could not find from jsonld", "none", "null", "", "failed", "pending"]

    # Calculate pre-run metric numbers
    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        has_webpage = is_downloaded_successfully(pub) and pub.get("review_url") not in [None, "NA", ""]
        if has_webpage:
            ld_critic = str(pub.get("jsonld_critic_name", "")).strip().lower()
            ld_rating = str(pub.get("jsonld_star_rating", "")).strip().lower()
            ai_critic = str(pub.get("ai_critic_name", "")).strip().lower()
            ai_rating = str(pub.get("ai_star_rating", "")).strip().lower()

            critic_missing = (ld_critic in bad_values) and (ai_critic in bad_values or ai_critic == "not_needed")
            rating_missing = (ld_rating in bad_values) and (ai_rating in bad_values or ai_rating == "not_needed")

            if not critic_missing and not rating_missing:
                earlier_completed += 1
            else:
                earlier_pending += 1

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

    for index, pub in enumerate(publishers, start=1):
        pub_id = pub.get("publisher_id", f"publisher_{index}")
        url = pub.get("review_url", "")
        has_webpage = is_downloaded_successfully(pub) and url and url.strip().upper() != "NA"

        ld_critic = str(pub.get("jsonld_critic_name", "")).strip()
        ld_rating = str(pub.get("jsonld_star_rating", "")).strip()
        ai_critic = str(pub.get("ai_critic_name", "")).strip()
        ai_rating = str(pub.get("ai_star_rating", "")).strip()

        # Is the data truly missing across both deterministic and AI fields?
        critic_missing = (ld_critic.lower() in bad_values) and (ai_critic.lower() in bad_values or ai_critic.lower() == "not_needed")
        rating_missing = (ld_rating.lower() in bad_values) and (ai_rating.lower() in bad_values or ai_rating.lower() == "not_needed")

        print(f"\n  [{index}/{len(publishers)}] [{pub_id}]")

        # Case 1: Non-webpage
        if not has_webpage:
            print("      Not processed- nonwebpage")
            movie_log_entry["publisher_details"][pub_id] = {"status": "Not processed- nonwebpage"}
            continue

        # Case 2: Both already found
        if not critic_missing and not rating_missing:
            print("      Not processed- both already found")
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "Not processed- both already found",
                "critic_name": ai_critic if ld_critic.lower() in bad_values else ld_critic,
                "star_rating": ai_rating if ld_rating.lower() in bad_values else ld_rating
            }
            continue

        # Case 3: Circuit Breaker
        attempts = pub.get("ai_metadata_parsing_attempts", 0)
        if attempts >= 5:
            print("      Not processed- max attempts reached (>= 5)")
            movie_log_entry["publisher_details"][pub_id] = {"status": "Not processed- max attempts reached"}
            continue

        # Case 4: Needs Processing
        if critic_missing and rating_missing:
            target_desc = "both to find"
        elif critic_missing:
            target_desc = "author to find"
        else:
            target_desc = "rating to find"

        print(f"      Processed- {target_desc}")
        pub["ai_metadata_parsing_attempts"] = attempts + 1
        movie_log_entry["processed"] += 1

        html_path = os.path.join(html_dir, f"webpage_{pub_id}_{movie_slug}.html")
        if not os.path.exists(html_path):
            alt_path = os.path.join(html_dir, f"webpage_{pub_id}.html")
            if os.path.exists(alt_path):
                html_path = alt_path
            else:
                print("      Result - failure")
                print("      found none")
                tracker.add_failure()
                movie_log_entry["failure"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": f"Processed- {target_desc}",
                    "result": "failure",
                    "reason": "HTML file missing on disk"
                }
                continue

        with open(html_path, "r", encoding="utf-8") as hf:
            raw_html = hf.read()

        cleaned_html = clean_html(raw_html)
        chunk_size = 800000
        chunks = [cleaned_html[i:i+chunk_size] for i in range(0, len(cleaned_html), chunk_size)]
        
        discovered_author = None
        discovered_rating = None
        used_model = "None"

        for idx, chunk in enumerate(chunks):
            extracted_data, model_success = extract_metadata_with_gemini(movie_name, chunk, prompt_template)

            if extracted_data:
                used_model = model_success
                new_critic = str(extracted_data.get("critic_name", "NA")).strip()
                new_rating = str(extracted_data.get("star_rating", "NA")).strip()

                # Strictly write to ai_ fields
                if critic_missing and not discovered_author and new_critic.lower() not in bad_values:
                    discovered_author = new_critic
                    pub["ai_critic_name"] = new_critic

                if rating_missing and not discovered_rating and new_rating.lower() not in bad_values:
                    discovered_rating = new_rating
                    pub["ai_star_rating"] = new_rating

            time.sleep(65)

            # Early exit check
            author_resolved = (not critic_missing) or (discovered_author is not None)
            rating_resolved = (not rating_missing) or (discovered_rating is not None)

            if author_resolved and rating_resolved:
                break

        # Calculate result status
        if target_desc == "both to find":
            if discovered_author and discovered_rating:
                result_str = "full success"
                tracker.add_success()
                movie_log_entry["success"] += 1
            elif discovered_author or discovered_rating:
                result_str = "partial success"
                tracker.add_success()
                movie_log_entry["success"] += 1
            else:
                result_str = "failure"
                tracker.add_failure()
                movie_log_entry["failure"] += 1
        else:
            if discovered_author or discovered_rating:
                result_str = "full success"
                tracker.add_success()
                movie_log_entry["success"] += 1
            else:
                result_str = "failure"
                tracker.add_failure()
                movie_log_entry["failure"] += 1

        print(f"      Result - {result_str}")

        # Format exact "only what found" discovery line
        found_parts = []
        if discovered_rating:
            found_parts.append(f"found rating - {discovered_rating}")
        if discovered_author:
            found_parts.append(f"author - {discovered_author}")

        if found_parts:
            print("      " + ", ".join(found_parts))
        else:
            print("      found none")

        # Save result metrics
        movie_log_entry["publisher_details"][pub_id] = {
            "status": f"Processed- {target_desc}",
            "result": result_str,
            "model": used_model,
            "discovered": {
                "ai_star_rating": discovered_rating,
                "ai_critic_name": discovered_author
            }
        }

        # Save review file state iteratively
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    # Save final structured log file
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
    target_files = [os.path.join(BASE_DIR, "data", "reviews", f"reviews_{slug}.json") 
                    for slug in live_slugs 
                    if os.path.exists(os.path.join(BASE_DIR, "data", "reviews", f"reviews_{slug}.json"))]

    if not target_files:
        print("[ERROR] No JSON files found for live movies.")
        return

    for json_path in target_files:
        process_movie_file(json_path, prompt_template)

if __name__ == "__main__":
    main()
