#!/usr/bin/env python3
"""
04-B-3_label.py
Classifies sentiment for UNRATED titles using Groq OSS models.
Reads new schema fields to verify gaps, and writes to `ai_sentiment_category`.
Uses (OSS1 -> OSS2) x 3 fallback loops with strict 15s TPM pacing.
"""

import builtins
import json
import os
import time
from datetime import datetime
from groq import Groq

# ---------------------------------------------------------------------------
# Global Print Override for Real-Time CI/CD Streaming
# ---------------------------------------------------------------------------
def print(*args, **kwargs):
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

# ---------------------------------------------------------------------------
# Path & Configuration Setup
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "classify_unrated.txt")
LIVE_MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

VALID_CATEGORIES = ["GOOD", "NEUTRAL", "BAD", "POSITIVE", "MIXED", "NEGATIVE"]

# ---------------------------------------------------------------------------
# Groq OSS API Setup
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GROQ_API_KEY")
if not API_KEY:
    print("[ERROR] GROQ_API_KEY environment variable not found!")
    exit(1)

client = Groq(
    api_key=API_KEY,
    timeout=20.0,
    max_retries=0
)

PRIMARY_MODEL = "openai/gpt-oss-120b"
BACKUP_MODEL = "openai/gpt-oss-20b"

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
# Helper Functions
# ---------------------------------------------------------------------------
def is_missing_star_rating(val):
    """Determines if the star rating is genuinely missing from the new schema fields."""
    if val in (None, "", "Na", "NA", "null", "FAILED", "PENDING", "NOT_NEEDED") or "could not find" in str(val).lower():
        return True
    try:
        float(val)
        return False
    except ValueError:
        return True

def is_valid_title(title):
    """Ensures title is a genuine extracted headline, not a placeholder, empty string, or failed string."""
    if not title:
        return False
    clean = str(title).strip()
    return clean != "" and clean.upper() not in ["PENDING", "FAILED"]

def clean_ai_response(text):
    """Strips markdown, JSON brackets, and whitespace to extract the category word."""
    text = text.strip().upper()
    text = text.replace("`", "").replace("*", "").replace('"', '').replace("'", "")
    for cat in VALID_CATEGORIES:
        if cat in text:
            return cat
    return text

def fetch_category_with_fallback(movie_name, clean_title, prompt_template):
    """Calls Groq OSS models with (OSS1 -> OSS2) x 3 fallback logic."""
    prompt = prompt_template.replace("{movie_name}", movie_name).replace("{clean_title}", clean_title)
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        print(f"      [Attempt {attempt}/{max_attempts}]")
        
        for model_name in [PRIMARY_MODEL, BACKUP_MODEL]:
            print(f"      [Attempting Model: {model_name}]")
            try:
                response = client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt.strip()}],
                    model=model_name,
                    max_tokens=200,      
                    temperature=0.0      
                )

                if response and response.choices:
                    raw_text = response.choices[0].message.content.strip()
                    category = clean_ai_response(raw_text)

                    if category in VALID_CATEGORIES:
                        return category, model_name
                    else:
                        print(f"      [Validation Failed] '{category}' is not a valid category.")
            except Exception as e:
                print(f"      [FAILED on {model_name}]: {str(e)}")

        if attempt < max_attempts:
            print("      [Both models failed. Waiting 5s before next retry loop...]")
            time.sleep(5)

    return None, None

def get_live_movie_slugs():
    slugs = []
    if not os.path.exists(LIVE_MOVIES_FILE):
        print(f"[ERROR] Live movies file not found at {LIVE_MOVIES_FILE}")
        return []

    with open(LIVE_MOVIES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        movie_list = data if isinstance(data, list) else data.get("movies", [])
        for movie in movie_list:
            if isinstance(movie, dict) and "slug" in movie:
                slugs.append(movie["slug"])
    return list(set(slugs))

# ---------------------------------------------------------------------------
# Pipeline Execution
# ---------------------------------------------------------------------------
def process_movie_file(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" CLASSIFYING UNRATED TITLES FOR: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_name = data.get("movie", {}).get("name", "Unknown Movie")
    movie_slug = data.get("movie", {}).get("slug", "unknown-slug")
    publishers = data.get("publishers", [])

    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "04-B-3_label.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    earlier_completed = 0
    earlier_pending = 0

    # Calculate Tracker Metrics based strictly on valid titles needing classification
    for pub in publishers:
        clean_title = pub.get("clean_title")
        ld_rating = pub.get("jsonld_star_rating")
        ai_rating = pub.get("ai_star_rating")
        
        rating_missing = is_missing_star_rating(ld_rating) and is_missing_star_rating(ai_rating)
        
        if is_valid_title(clean_title) and rating_missing:
            current_category = str(pub.get("ai_sentiment_category", "PENDING")).strip().upper()
            if current_category in VALID_CATEGORIES:
                earlier_completed += 1
            else:
                earlier_pending += 1

    tracker = PipelineTracker("Sentiment Labeling (Groq OSS)", earlier_completed, earlier_pending)

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

    updated_file = False

    for pub in publishers:
        pub_id = pub.get("publisher_id", "Unknown")
        clean_title = pub.get("clean_title")
        
        ld_rating = pub.get("jsonld_star_rating")
        ai_rating = pub.get("ai_star_rating")
        rating_missing = is_missing_star_rating(ld_rating) and is_missing_star_rating(ai_rating)
        
        ai_category = str(pub.get("ai_sentiment_category", "PENDING")).strip().upper()

        print(f"\n  [*] Processing [{pub_id}]")

        # Skip non-webpages or placeholder titles
        if not is_valid_title(clean_title):
            print("      Not processed- nonwebpage / title pending or failed")
            continue

        # Skip publishers that already have star ratings
        if not rating_missing:
            print("      Not processed- publisher has valid star rating")
            continue

        # Skip already completed items
        if ai_category in VALID_CATEGORIES:
            print(f"      Not processed- already classified as {ai_category}")
            continue

        print(f"      Processed- unrated title found")
        print(f"      Title: {clean_title}")
        
        movie_log_entry["processed"] += 1

        category, used_model = fetch_category_with_fallback(movie_name, clean_title, prompt_template)

        if category:
            pub["ai_sentiment_category"] = category
            print("      Result - full success")
            print(f"      found sentiment - {category}")
            tracker.add_success()
            movie_log_entry["success"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "Processed",
                "result": "full success",
                "model": used_model,
                "ai_sentiment_category": category
            }
            updated_file = True
        else:
            print("      Result - failure")
            print("      found none (API exhaust or invalid output)")
            tracker.add_failure()
            movie_log_entry["failure"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "Processed",
                "result": "failure",
                "reason": "API exhausted or failed validation"
            }

        # 15-second pacing completely resets Groq's 8,000 TPM limit
        print("      [Pacing] Waiting 15s to respect Groq TPM limits...")
        time.sleep(15)

    if updated_file:
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
    print("[STEP 1] Validating Environment...")
    if not os.path.exists(PROMPT_FILE):
        print(f"[FATAL] Prompt file missing: {PROMPT_FILE}")
        return

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    print("[STEP 2] Loading live movies...")
    slugs = get_live_movie_slugs()
    if not slugs:
        print("[ERROR] No live movies found.")
        return

    target_files = []
    for slug in slugs:
        filepath = os.path.join(REVIEWS_DIR, f"reviews_{slug}.json")
        if os.path.exists(filepath):
            target_files.append(filepath)

    print(f"[STEP 3] Found {len(target_files)} review files. Starting loop...")
    for file_path in target_files:
        process_movie_file(file_path, prompt_template)

if __name__ == "__main__":
    main()
