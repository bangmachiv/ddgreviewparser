#!/usr/bin/env python3
"""
04-A-2_clean.py
Uses Google's Gemini API to clean raw article titles.
"""

import json
import os
import glob
import re
import time
import html  
from datetime import datetime
from google import genai
from google.genai import errors

# ---------------------------------------------------------------------------
# Configuration & Absolute Pathing
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "prompt_clean_titles.txt")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# ---------------------------------------------------------------------------
# Gemini API Setup
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("[ERROR] GEMINI_API_KEY environment variable not found!")
    exit(1)

client = genai.Client(api_key=API_KEY)

MODEL_CONFIG = [
    {"name": "gemini-3.5-flash-lite", "priority": 1, "enabled": True},
    {"name": "gemini-3.1-flash-lite", "priority": 2, "enabled": True}
]

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
# Validation Helpers
# ---------------------------------------------------------------------------
def extract_words(text):
    if not text:
        return []
    return re.findall(r'\w+', text.lower(), re.UNICODE)

def validate_cleaned_title(cleaned_title, original_title):
    if not cleaned_title or not cleaned_title.strip():
        return False
    clean_words = extract_words(cleaned_title)
    if not clean_words:
        return False
    original_words_set = set(extract_words(original_title))
    for word in clean_words:
        if word not in original_words_set:
            print(f"      [Validation Fail] Word '{word}' is not in the original title!")
            return False
    return True

# ---------------------------------------------------------------------------
# Core Gemini Cleaning Logic
# ---------------------------------------------------------------------------
def clean_title_with_gemini(movie_name, raw_title, models_config, prompt_template):
    active_models = sorted(
        [m for m in models_config if m.get("enabled", True)],
        key=lambda x: x.get("priority", 999)
    )

    prompt = prompt_template.format(movie_name=movie_name, raw_title=raw_title)

    for model_info in active_models:
        model_name = model_info["name"]
        print(f"      [Attempting Model: {model_name}]")

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )

            if response and response.text:
                cleaned = response.text.strip()
                if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
                    cleaned = cleaned[1:-1].strip()

                if validate_cleaned_title(cleaned, raw_title):
                    print(f"      [Success with {model_name}]")
                    return cleaned
                else:
                    print(f"      [Output Rejected] Output failed strict word containment check.")

        except errors.APIError as e:
            print(f"      [API Error on {model_name}]: {e}")
        except Exception as e:
            print(f"      [Unexpected Error on {model_name}]: {e}")

        print("      [Waiting 5 seconds before model fallback attempt...]")
        time.sleep(5)  

    return None

# ---------------------------------------------------------------------------
# File Processing & Pipeline Integration
# ---------------------------------------------------------------------------
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
        search_path = os.path.join(BASE_DIR, "data", "movies", "*.json")
        for file_path in glob.glob(search_path):
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    slug = data.get("slug") or data.get("movie", {}).get("slug")
                    if slug:
                        slugs.append(slug)
                except Exception:
                    pass
    return list(set(slugs))

def process_cleaning_for_movie(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" CLEANING TITLES FOR LIVE MOVIE FILE: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_name = data.get("movie", {}).get("name")
    movie_slug = data.get("movie", {}).get("slug")
    publishers = data.get("publishers", [])

    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "04-A-2_clean.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    # -------------------------------------------------------------------------
    # Pre-Scan Metrics Calculation
    # -------------------------------------------------------------------------
    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        article_title = pub.get("article_title", "PENDING")
        clean_title = pub.get("clean_title", "PENDING")

        # Candidates are publishers that have a raw article title successfully extracted
        if article_title not in ["PENDING", "FAILED", None, ""]:
            if clean_title not in ["PENDING", "FAILED", None, ""]:
                earlier_completed += 1
            else:
                earlier_pending += 1

    tracker = PipelineTracker("Titles Cleaned (Gemini)", earlier_completed, earlier_pending)

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

    # -------------------------------------------------------------------------
    # Execution Loop
    # -------------------------------------------------------------------------
    for index, pub in enumerate(publishers, start=1):
        pub_id = pub.get("publisher_id", f"publisher_{index}")
        raw_title = pub.get("article_title", "PENDING")
        existing_clean_title = pub.get("clean_title", "PENDING")

        # 1. Skip if no raw title is available for cleaning
        if raw_title in ["PENDING", "FAILED", None, ""]:
            continue

        # 2. Skip if already successfully cleaned
        if existing_clean_title not in ["PENDING", "FAILED", None, ""]:
            print(f"  [{index}/{len(publishers)}] [SKIP] {pub_id} title already cleaned.")
            continue

        print(f"\n  [*] Processing [{pub_id}]...")
        print(f"      Raw Title: {raw_title}")

        movie_log_entry["processed"] += 1
        cleaned = clean_title_with_gemini(movie_name, raw_title, MODEL_CONFIG, prompt_template)

        if cleaned:
            # Decode HTML entities right before assigning to the pub dictionary
            cleaned = html.unescape(cleaned)

            pub["clean_title"] = cleaned
            print(f"      [SUCCESS] Saved clean_title: {cleaned}")
            tracker.add_success()
            movie_log_entry["success"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "SUCCESS",
                "clean_title": cleaned
            }
        else:
            pub["clean_title"] = "FAILED"
            print(f"      [FAILED] Output invalid or null across all models.")
            tracker.add_failure()
            movie_log_entry["failure"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "FAILED",
                "reason": "Validation failed or API error"
            }

        # Be nice to the API limits
        print("      [Waiting 10 seconds before next API call...]")
        time.sleep(10)

        # Save reviews JSON incrementally
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] Could not save updated review file: {e}")

    # Finalize log summary
    movie_log_entry["new_completed"] = earlier_completed + movie_log_entry["success"]
    movie_log_entry["new_pending"] = earlier_pending - movie_log_entry["success"]

    # Safely write to 04-A-2_clean.json
    script_log_data = {}
    if os.path.exists(script_log_path) and os.path.getsize(script_log_path) > 0:
        try:
            with open(script_log_path, "r", encoding="utf-8") as lf:
                script_log_data = json.load(lf)
        except json.JSONDecodeError:
            pass

    timestamp = datetime.now().astimezone().isoformat()
    script_log_data[timestamp] = movie_log_entry

    try:
        with open(script_log_path, "w", encoding="utf-8") as lf:
            json.dump(script_log_data, lf, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[ERROR] Could not write to log file: {e}")

    tracker.print_summary()


def main():
    print("================================================================")
    print(" FORENSIC DEBUGGING LOG: PATHS & FILESYSTEM")
    print("================================================================")
    print(f"[*] Raw __file__ path : {__file__}")
    print(f"[*] Base Directory    : {BASE_DIR}")
    print(f"[*] Expected Prompt   : {PROMPT_FILE}")
    print("\n[*] Python's view of files in Prompts Directory:")

    try:  
        prompt_dir = os.path.join(BASE_DIR, "prompts")
        if not os.path.exists(prompt_dir):
            print(f"    [ERROR] Prompts directory not found at {prompt_dir}")
        else:
            files = os.listdir(prompt_dir)  
            for f in files:  
                # Highlight anything that has 'prompt' in the name to catch typos  
                if "prompt" in f.lower():  
                    print(f"    ---> SUSPECT FOUND: '{f}'")  
                else:  
                    print(f"    - {f}")  
    except Exception as e:  
        print(f"    [ERROR] Could not read directory: {e}")  
    print("================================================================\n")  

    print("[STEP 1] Loading prompt template...")  
    if not os.path.exists(PROMPT_FILE):  
        print(f"[FATAL ERROR] The exact file '{PROMPT_FILE}' does not exist according to Python.")  
        return  
        
    with open(PROMPT_FILE, "r", encoding="utf-8") as pf:  
        prompt_template = pf.read()  

    print("[STEP 2] Fetching live movies for title cleaning...")  
    live_slugs = get_live_movie_slugs()  

    if not live_slugs:  
        print("[ERROR] No live movies found. Exiting.")  
        return  

    target_files = []  
    for slug in live_slugs:  
        review_file = os.path.join(BASE_DIR, "data", "reviews", f"reviews_{slug}.json")  
        if os.path.exists(review_file):  
            target_files.append(review_file)  

    print("\n[STEP 3] Running Gemini cleaning pipeline...")  
    for json_path in target_files:  
        process_cleaning_for_movie(json_path, prompt_template)

if __name__ == "__main__":
    main()
