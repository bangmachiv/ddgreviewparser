#!/usr/bin/env python3
"""
03-A-2_adjudicate.py
Semantically evaluates extracted article text using Gemma 4 31B (with 26B fallback) 
via the Google Gemini API to verify if the content is a genuine movie review.
Updates the publisher state machine with a YES/NO 'content_adjudication' flag.
"""

import os
import json
import glob
import time
import sys
import traceback
from datetime import datetime

try:
    from google import genai
    from google.genai import types
    from google.genai import errors
except ImportError:
    print("[FATAL ERROR] google-genai package is missing. Run: pip install google-genai")
    sys.exit(1)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
WEBCONTENT_DIR = os.path.join(BASE_DIR, "data", "webcontent")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
PROMPT_FILE = os.path.join(PROMPTS_DIR, "adjudicate_review.txt")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("[FATAL ERROR] GEMINI_API_KEY environment variable is not set.")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

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

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def clean_json_response(raw_text):
    """Removes markdown code blocks if the model wrapped the JSON."""
    clean_text = raw_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    return clean_text.strip()

def call_gemini_api(model_name, prompt):
    """Executes a single text generation call to the specified Gemma model."""
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        
        if not getattr(response, "candidates", None) or not response.candidates:
            print(f"      [DEBUG ERROR] API call succeeded on {model_name}, but candidates payload is empty. Raw response object: {response}")
            return None

        text_val = response.text
        if text_val and text_val.strip():
            return text_val
        else:
            finish_reason = response.candidates[0].finish_reason if response.candidates else "Unknown"
            print(f"      [DEBUG ERROR] Model {model_name} returned empty text. Candidate finish reason: {finish_reason}")

    except errors.APIError as e:
        # Captures explicit API rejections (e.g., 429 quota exceeded, 503 capacity, 400 bad request)
        print(f"      [API ERROR on {model_name}]: Code: {getattr(e, 'code', 'N/A')}, Message: {getattr(e, 'message', str(e))}")
    except Exception as e:
        # Captures network drops, timeout errors, or unexpected SDK crashes
        print(f"      [UNEXPECTED ERROR on {model_name}]: {type(e).__name__}: {str(e)}")
        print(f"      [TRACEBACK]: {traceback.format_exc().strip().replace(chr(10), ' | ')}")

    return None

def process_single_movie(json_path: str, prompt_template: str):
    """Processes adjudication for a single movie's JSON file."""
    print("\n" + "=" * 80)
    print(f" CONTENT ADJUDICATION FOR: {json_path}")
    print("=" * 80)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Could not read {json_path}: {e}")
        return

    movie_name = data.get("movie", {}).get("name")
    movie_slug = data.get("movie", {}).get("slug")
    if not movie_slug or not movie_name:
        print(f"[ERROR] Missing 'slug' or 'name' in {json_path}. Skipping.")
        return

    content_dir = os.path.join(WEBCONTENT_DIR, movie_slug)
    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "03b_adjudicate.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    publishers = data.get("publishers", [])

    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        if pub.get("classified_by") == "AI" and pub.get("webpage_extraction_successful") == "SUCCESS":
            adj_status = pub.get("content_adjudication", "PENDING")
            if adj_status in ["YES", "NO"]:
                earlier_completed += 1
            else:
                earlier_pending += 1

    tracker = PipelineTracker("Content Adjudicated", earlier_completed, earlier_pending)

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

    data_changed = False

    for pub in publishers:
        pub_id = pub.get("publisher_id")
        pub_name = pub.get("publisher_name")
        classified_by = pub.get("classified_by")
        download_status = pub.get("webpage_extraction_successful")
        adj_status = pub.get("content_adjudication", "PENDING")

        # Execution Gate: Target AI classified + successfully extracted publishers
        if classified_by != "AI" or download_status != "SUCCESS":
            continue

        if adj_status in ["YES", "NO"]:
            print(f"  [SKIP] {pub_name} already adjudicated ({adj_status}).")
            continue

        content_file = os.path.join(content_dir, f"content_{pub_id}_{movie_slug}.txt")
        if not os.path.exists(content_file):
            print(f"  [WARNING] Content file missing for {pub_name}. Skipping.")
            continue

        print(f"\n--- Adjudicating {pub_name} ---")
        movie_log_entry["processed"] += 1

        try:
            with open(content_file, "r", encoding="utf-8") as f:
                article_text = f.read()

            # Truncate text strictly to 25,000 characters to cap payloads at ~6,250 tokens
            if len(article_text) > 25000:
                article_text = article_text[:25000] + "\n...[TRUNCATED]"

            prompt = prompt_template.replace("{MOVIE_TITLE}", movie_name)\
                                    .replace("{ARTICLE_TEXT}", article_text)

            raw_response = None
            used_model = None
            MAX_LOOPS = 3

            for attempt in range(1, MAX_LOOPS + 1):
                # -------------------------------------------------------------
                # Attempt 1: Gemma 31B
                # -------------------------------------------------------------
                print(f"      [Attempting Model: gemma-4-31b-it (Loop {attempt}/{MAX_LOOPS})]")
                raw_response = call_gemini_api("gemma-4-31b-it", prompt)
                if raw_response:
                    used_model = "gemma-4-31b-it"
                    break
                
                print("      [API FAILURE] gemma-4-31b-it failed. Waiting 10 seconds before 26B fallback...")
                time.sleep(10)

                # -------------------------------------------------------------
                # Attempt 2: Gemma 26B Fallback
                # -------------------------------------------------------------
                print(f"      [Attempting Model: gemma-4-26b-a4b-it (Loop {attempt}/{MAX_LOOPS})]")
                raw_response = call_gemini_api("gemma-4-26b-a4b-it", prompt)
                if raw_response:
                    used_model = "gemma-4-26b-a4b-it"
                    break
                
                print("      [API FAILURE] gemma-4-26b-a4b-it fallback failed.")
                if attempt < MAX_LOOPS:
                    print("      [RETRYING] Waiting 10 seconds before restarting 31B/26B cascade loop...")
                    time.sleep(10)

            # -------------------------------------------------------------
            # Resolution & 60-Second Inter-Publisher Cool-off
            # -------------------------------------------------------------
            if raw_response:
                clean_response = clean_json_response(raw_response)
                
                try:
                    parsed_json = json.loads(clean_response)
                    is_review = str(parsed_json.get("is_movie_review", "")).strip().upper()
                    
                    if is_review in ["YES", "NO"]:
                        print(f"  [SUCCESS] Adjudicated via {used_model}: {is_review}")
                        pub["content_adjudication"] = is_review
                        data_changed = True
                        
                        tracker.add_success()
                        movie_log_entry["success"] += 1
                        movie_log_entry["publisher_details"][pub_id] = {
                            "status": "SUCCESS",
                            "adjudication": is_review,
                            "model": used_model
                        }
                    else:
                        print(f"  [FAILED] Model {used_model} returned valid JSON but missing/invalid 'is_movie_review' key. Parsed output: {parsed_json}")
                        tracker.add_failure()
                        movie_log_entry["failure"] += 1
                        movie_log_entry["publisher_details"][pub_id] = {
                            "status": "FAILED",
                            "reason": "Missing/Invalid Key in JSON"
                        }
                        
                except json.JSONDecodeError as e:
                    print(f"  [FAILED] JSON Decode Error on {used_model}: {e}. Raw model output was: {raw_response}")
                    tracker.add_failure()
                    movie_log_entry["failure"] += 1
                    movie_log_entry["publisher_details"][pub_id] = {
                        "status": "FAILED",
                        "reason": "JSON Decode Error"
                    }
                
                # The LLM API successfully returned a response (consuming tokens). Apply the 60s TPM cool-off.
                print("      [RATE LIMIT] Successful LLM API return. Sleeping 60 seconds to clear TPM buffer before next publisher...")
                time.sleep(60)

            else:
                print(f"  [FAILED] Publisher exhausted all {MAX_LOOPS} loops of the 31B/26B cascade.")
                tracker.add_failure()
                movie_log_entry["failure"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": "FAILED",
                    "reason": "Cascade Exhausted"
                }

        except Exception as e:
            print(f"  [ERROR] File processing or systemic failure on {pub_name}: {e}")
            tracker.add_failure()
            movie_log_entry["failure"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "FAILED",
                "reason": str(e)
            }

    if data_changed:
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] Could not save updated review file: {e}")

    # Finalize Log
    movie_log_entry["new_completed"] = earlier_completed + movie_log_entry["success"]
    movie_log_entry["new_pending"] = earlier_pending - movie_log_entry["success"]

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
    print("=" * 80)
    print(" 03B: GEMMA CONTENT ADJUDICATION")
    print("=" * 80)
    
    if not os.path.exists(PROMPT_FILE):
        print(f"[FATAL ERROR] Prompt file missing: {PROMPT_FILE}")
        sys.exit(1)

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt_template = f.read()
        
    target_files = glob.glob(os.path.join(REVIEWS_DIR, "reviews_*.json"))

    if not target_files:
        print("[ERROR] No JSON files found in data/reviews/ directory.")
        return

    print(f"[INFO] Found {len(target_files)} movie review file(s) for adjudication.")

    for json_path in target_files:
        process_single_movie(json_path, prompt_template)

    print("\n" + "=" * 40)
    print(" ALL ADJUDICATIONS COMPLETED")
    print("=" * 40)

if __name__ == "__main__":
    main()
