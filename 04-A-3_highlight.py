#!/usr/bin/env python3
"""
04-A-3_highlight.py
Uses Groq API with Qwen models (prioritizing qwen3.8-27b) to extract highlight 
keywords from cleaned article titles, complete with <think> tag sanitization,
raw text debugging, and real-time stdout flushing for GitHub Actions.
"""

import builtins
import json
import os
import glob
import re
import time
import html
from datetime import datetime
from groq import Groq

# ---------------------------------------------------------------------------
# Global Print Override for Real-Time CI/CD Streaming
# ---------------------------------------------------------------------------
def print(*args, **kwargs):
    """Overrides the default print function to force flush=True every time."""
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "find_title_highlight.txt")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# ---------------------------------------------------------------------------
# Groq API Setup & Optimized Model Configuration (3.8-27b as Primary)
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("[ERROR] GROQ_API_KEY environment variable not found!")
    exit(1)

client = Groq(api_key=GROQ_API_KEY)

QWEN_MODELS = [
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b"
]

# Global round-robin index
current_model_index = 0

def get_next_qwen_pair():
    """Returns (primary_model, fallback_model) alternating on each invocation."""
    global current_model_index
    primary = QWEN_MODELS[current_model_index % len(QWEN_MODELS)]
    fallback = QWEN_MODELS[(current_model_index + 1) % len(QWEN_MODELS)]
    current_model_index += 1
    return primary, fallback

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
# Validation & Formatting Logic
# ---------------------------------------------------------------------------
def strip_reasoning_and_markdown(text: str) -> str:
    """Strips <think>...</think> blocks and Markdown code fences."""
    # Remove reasoning thought blocks if present
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    
    # Strip Markdown JSON fences
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
        
    return text.strip()

def extract_keywords_from_payload(parsed_json):
    """Handles both flat lists and dictionary-wrapped lists."""
    if isinstance(parsed_json, list):
        return parsed_json
    if isinstance(parsed_json, dict):
        for key in ["keywords", "highlights", "phrases", "result", "output", "words"]:
            if key in parsed_json and isinstance(parsed_json[key], list):
                return parsed_json[key]
        for val in parsed_json.values():
            if isinstance(val, list):
                return val
    return None

def process_and_validate_highlight(clean_title, raw_response_text):
    """
    Validates Qwen's response and injects asterisks around the first occurrence
    of valid emotion keywords.
    """
    # Print exact raw text for CI/CD debugging visibility
    print(f"      [DEBUG RAW TEXT FROM MODEL]: {repr(raw_response_text)}")

    if not raw_response_text or not raw_response_text.strip():
        print("      [FAIL] Model returned empty response.")
        return None

    try:
        raw_json = strip_reasoning_and_markdown(raw_response_text)
        parsed = json.loads(raw_json)
        keywords = extract_keywords_from_payload(parsed)
    except Exception as e:
        print(f"      [FAIL] Failed to parse JSON: {e}")
        return None

    if keywords is None or not isinstance(keywords, list):
        print(f"      [FAIL] Could not extract a list from response: {parsed}")
        return None

    if len(keywords) == 0:
        print("      [FAIL] 0 keywords returned.")
        return None
    if len(keywords) > 3:
        print(f"      [FAIL] Too many keywords returned ({len(keywords)}). Max is 3.")
        return None

    clean_title_clean = html.unescape(clean_title)
    clean_title_lower = clean_title_clean.lower()
    valid_keywords = []

    for kw in keywords:
        kw_str = str(kw).strip()
        if not kw_str:
            continue

        # Rule: Max 3 words per phrase
        if len(kw_str.split()) > 3:
            print(f"      [FAIL] Phrase '{kw_str}' has more than 3 words.")
            return None

        # Rule: Substring containment check
        if kw_str.lower() not in clean_title_lower:
            print(f"      [FAIL] Phrase '{kw_str}' is NOT found in original title.")
            return None

        valid_keywords.append(kw_str)

    if not valid_keywords:
        print("      [FAIL] No valid keywords passed containment check.")
        return None

    # Sort descending by length so longer phrases are highlighted first
    valid_keywords.sort(key=len, reverse=True)

    highlighted_title = clean_title_clean
    for kw in valid_keywords:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        # Substitute only the first occurrence
        highlighted_title = pattern.sub(f"*{kw}*", highlighted_title, count=1)

    return highlighted_title

# ---------------------------------------------------------------------------
# Pipeline Execution
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

def fetch_highlights_with_alternating_qwen(movie_name, clean_title, prompt_template):
    prompt = prompt_template.replace("{movie_name}", movie_name).replace("{clean_title}", clean_title)
    primary_model, fallback_model = get_next_qwen_pair()
    attempts = [primary_model, fallback_model]

    for model_name in attempts:
        print(f"      [Attempting Groq Model: {model_name}]")
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "user", "content": prompt}
                ],
                model=model_name,
                temperature=0.0,
                max_tokens=1000
            )
            
            raw_text = chat_completion.choices[0].message.content
            if raw_text:
                raw_text = raw_text.strip()
                # Check validation before accepting this model's response
                highlighted = process_and_validate_highlight(clean_title, raw_text)
                if highlighted:
                    return highlighted, model_name
                else:
                    print("      [Validation Failed for this model output, attempting fallback...]")
        except Exception as e:
            print(f"      [API Error on {model_name}]: {e}")

        print("      [Waiting 3s before fallback model attempt...]")
        time.sleep(3)

    return None, None

def process_movie_file(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" HIGHLIGHTING TITLES FOR: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_name = data.get("movie", {}).get("name", "Unknown Movie")
    movie_slug = data.get("movie", {}).get("slug", "unknown-slug")
    publishers = data.get("publishers", [])

    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "04-A-3_highlight.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    # -------------------------------------------------------------------------
    # Pre-Scan Metrics Calculation
    # -------------------------------------------------------------------------
    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        clean_title = pub.get("clean_title", "PENDING")
        highlighted_title = pub.get("highlighted_title", "PENDING")

        if clean_title not in ["PENDING", "FAILED", None, ""]:
            if highlighted_title not in ["PENDING", "FAILED", None, ""]:
                earlier_completed += 1
            else:
                earlier_pending += 1

    tracker = PipelineTracker("Titles Highlighted (Groq Qwen)", earlier_completed, earlier_pending)

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
        clean_title = pub.get("clean_title", "PENDING")
        existing_highlight = pub.get("highlighted_title", "PENDING")

        if clean_title in ["PENDING", "FAILED", None, ""]:
            continue

        if existing_highlight not in ["PENDING", "FAILED", None, ""]:
            print(f"  [{index}/{len(publishers)}] [SKIP] {pub_id} already highlighted.")
            continue

        print(f"\n  [*] Processing [{pub_id}]...")
        print(f"      Clean Title: {clean_title}")

        movie_log_entry["processed"] += 1
        highlighted_title, used_model = fetch_highlights_with_alternating_qwen(movie_name, clean_title, prompt_template)

        if highlighted_title:
            pub["highlighted_title"] = highlighted_title
            print(f"      [SUCCESS with {used_model}] Saved highlighted_title: {highlighted_title}")
            tracker.add_success()
            movie_log_entry["success"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "SUCCESS",
                "model": used_model,
                "highlighted_title": highlighted_title
            }
        else:
            pub["highlighted_title"] = "FAILED"
            print(f"      [FAILED] Field 'highlighted_title' marked as FAILED.")
            tracker.add_failure()
            movie_log_entry["failure"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "FAILED",
                "reason": "Validation failed or API error"
            }

        print("      [Waiting 8 seconds before next API call...]")
        time.sleep(8)

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] Could not save updated review file: {e}")

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
                if "prompt" in f.lower() or "highlight" in f.lower():  
                    print(f"    ---> SUSPECT FOUND: '{f}'")  
                else:  
                    print(f"    - {f}")  
    except Exception as e:  
        print(f"    [ERROR] Could not read directory: {e}")  
    print("================================================================\n")  

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

    print("\n✅ All highlighting completed successfully.")


if __name__ == "__main__":
    main()
