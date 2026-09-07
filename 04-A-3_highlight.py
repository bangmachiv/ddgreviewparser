#!/usr/bin/env python3
"""
04-A-3_highlight.py
Uses Groq API with qwen3.8-27b as the primary model (extracts 0-3 words, reasoning ON).
If 3.8 fails, falls back to qwen3.6-27b using a strict, multiple-choice index prompt 
(find_title_highlight_lite.txt) for exactly 1-word extraction with reasoning OFF.
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
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "find_title_highlight.txt")
FALLBACK_PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "find_title_highlight_lite.txt")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# ---------------------------------------------------------------------------
# Groq API Setup
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("[ERROR] GROQ_API_KEY environment variable not found!")
    exit(1)

client = Groq(api_key=GROQ_API_KEY)

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
# Core Helpers
# ---------------------------------------------------------------------------
def strip_reasoning_and_markdown(text: str) -> str:
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

# ---------------------------------------------------------------------------
# Primary Validation Logic (For 3.8 string responses)
# ---------------------------------------------------------------------------
def extract_keywords_from_payload(parsed_json):
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

def process_and_validate_primary(clean_title, raw_response_text):
    """Validates the standard string extraction from the primary model (3.8)."""
    print(f"      [DEBUG RAW TEXT FROM PRIMARY]: {repr(raw_response_text)}")

    if not raw_response_text or not raw_response_text.strip():
        print("      [FAIL] Primary model returned empty response.")
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
        print("      [FAIL] Primary returned empty array []. No highlight.")
        return None

    if len(keywords) > 3:
        print(f"      [FAIL] Primary returned too many keywords ({len(keywords)}). Max is 3.")
        return None

    clean_title_clean = html.unescape(clean_title)
    clean_title_lower = clean_title_clean.lower()
    
    valid_keywords = []
    cumulative_word_count = 0

    for kw in keywords:
        kw_str = str(kw).strip()
        if not kw_str:
            continue

        if kw_str.lower() not in clean_title_lower:
            print(f"      [FAIL] Phrase '{kw_str}' is NOT found in original title.")
            return None

        word_count = len(kw_str.split())
        cumulative_word_count += word_count
        valid_keywords.append(kw_str)

    if not valid_keywords:
        print("      [FAIL] No valid keywords passed containment check.")
        return None

    if cumulative_word_count > 3:
        print(f"      [FAIL] Cumulative word count ({cumulative_word_count}) > 3.")
        return None

    valid_keywords.sort(key=len, reverse=True)
    highlighted_title = clean_title_clean

    for kw in valid_keywords:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        highlighted_title = pattern.sub(f"*{kw}*", highlighted_title, count=1)

    return highlighted_title


# ---------------------------------------------------------------------------
# Fallback Validation Logic (For 3.6 multiple-choice responses)
# ---------------------------------------------------------------------------
def generate_fallback_candidates(clean_title):
    """
    Splits the title into individual words and strips punctuation to create
    a dictionary of candidate strings matched to integer index keys.
    """
    words_raw = clean_title.split()
    candidates = {}
    idx = 1
    
    for w in words_raw:
        # Strip trailing/leading punctuation to mimic "mechanically generated" lists
        clean_word = w.strip(".,!?:;'\"()[]{}")
        if clean_word:
            if clean_word not in candidates.values():
                candidates[str(idx)] = clean_word
                idx += 1
                
    return candidates

def process_and_validate_fallback(clean_title, raw_response_text, candidates_dict):
    """Validates the multiple-choice integer index from the fallback model (3.6)."""
    print(f"      [DEBUG RAW TEXT FROM FALLBACK]: {repr(raw_response_text)}")

    if not raw_response_text or not raw_response_text.strip():
        print("      [FAIL] Fallback model returned empty response.")
        return None

    try:
        raw_json = strip_reasoning_and_markdown(raw_response_text)
        parsed = json.loads(raw_json)
        
        # Expecting format: [7] or []
        if isinstance(parsed, list):
            if len(parsed) == 0:
                print("      [INFO] Fallback explicitly returned []. No highlight selected.")
                return None
            selected_index_str = str(parsed[0]).strip()
        elif isinstance(parsed, (int, str)):
            selected_index_str = str(parsed).strip()
        else:
            print(f"      [FAIL] Unexpected JSON structure: {parsed}")
            return None
            
    except Exception as e:
        print(f"      [FAIL] Failed to parse JSON response: {e}")
        return None

    if not selected_index_str.isdigit():
        print(f"      [FAIL] Response '{selected_index_str}' is not a valid integer index.")
        return None

    if selected_index_str not in candidates_dict:
        print(f"      [FAIL] Index '{selected_index_str}' is out of range.")
        return None

    chosen_phrase = candidates_dict[selected_index_str]
    clean_title_clean = html.unescape(clean_title)
    
    pattern = re.compile(re.escape(chosen_phrase), re.IGNORECASE)
    highlighted_title = pattern.sub(f"*{chosen_phrase}*", clean_title_clean, count=1)

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

def fetch_highlight_for_review(movie_name, clean_title, primary_prompt_template, fallback_prompt_template):
    # 1. Prepare Primary Prompt
    primary_prompt = primary_prompt_template.replace("{movie_name}", movie_name).replace("{clean_title}", clean_title)
    
    # 2. Prepare Fallback Prompt
    candidates = generate_fallback_candidates(clean_title)
    candidates_json = json.dumps(candidates, ensure_ascii=False)
    fallback_prompt = (fallback_prompt_template
                       .replace("{movie_name}", movie_name)
                       .replace("{clean_title}", clean_title)
                       .replace("{candidates_json}", candidates_json))

    primary_model = "qwen/qwen3.8-27b"
    fallback_model = "qwen/qwen3.6-27b"
    max_retries = 2
    
    # --- STEP 1: Exhaust the Primary Model (3.8) ---
    print(f"      [Attempting Primary Model: {primary_model}]")
    for attempt in range(max_retries + 1):
        try:
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": primary_prompt}],
                model=primary_model,
                temperature=0.0,
                max_tokens=250 
            )

            raw_text = chat_completion.choices[0].message.content
            if raw_text:
                raw_text = raw_text.strip()
                highlighted = process_and_validate_primary(clean_title, raw_text)
                
                if highlighted:
                    return highlighted, primary_model
                else:
                    print("      [Validation Failed for Primary output. Aborting retries for this model.]")
                    break 
        except Exception as e:
            error_msg = str(e)
            print(f"      [API Error on {primary_model}] (Attempt {attempt+1}/{max_retries+1}): {error_msg}")

            if "429" in error_msg or "rate_limit" in error_msg.lower() or "timeout" in error_msg.lower():
                if attempt < max_retries:
                    wait_time = (attempt + 1) * 10
                    print(f"      [Rate Limit Hit] Buffering and waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
            else:
                break 

    # --- STEP 2: Ultimate Fallback (3.6) with 1-Word Index Selection ---
    print(f"      [Primary Exhausted] Switching to Backup Model: {fallback_model} (Thinking=None, Index Selection)...")
    for attempt in range(max_retries + 1):
        try:
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": fallback_prompt}],
                model=fallback_model,
                temperature=0.0,
                max_tokens=250,
                reasoning_effort="none"  # <-- THINKING OFF FOR 3.6
            )

            raw_text = chat_completion.choices[0].message.content
            if raw_text:
                raw_text = raw_text.strip()
                # Run the integer index validator
                highlighted = process_and_validate_fallback(clean_title, raw_text, candidates)
                
                if highlighted:
                    return highlighted, fallback_model
                else:
                    print("      [Validation Failed for Backup output.]")
                    break
        except Exception as e:
            error_msg = str(e)
            print(f"      [API Error on {fallback_model}] (Attempt {attempt+1}/{max_retries+1}): {error_msg}")

            if "429" in error_msg or "rate_limit" in error_msg.lower() or "timeout" in error_msg.lower():
                if attempt < max_retries:
                    wait_time = (attempt + 1) * 10
                    print(f"      [Rate Limit Hit] Buffering and waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
            else:
                break

    return None, None

def process_movie_file(json_path, primary_prompt_template, fallback_prompt_template):
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

        # Execute dual-model API request logic
        highlighted_title, used_model = fetch_highlight_for_review(movie_name, clean_title, primary_prompt_template, fallback_prompt_template)

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

        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] Could not save updated review file: {e}")

        print("      [Pacing Buffer] Waiting 15 seconds to ensure 4 requests/min cadence...")
        time.sleep(15)

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
    print(f"[*] Expected Prompts  : {PROMPT_FILE} & {FALLBACK_PROMPT_FILE}")
    
    print("\n[STEP 1] Validating Environment...")
    if not os.path.exists(PROMPT_FILE):
        print(f"[FATAL] Primary prompt file missing: {PROMPT_FILE}")
        return
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        primary_prompt_template = f.read()

    if not os.path.exists(FALLBACK_PROMPT_FILE):
        print(f"[FATAL] Fallback prompt file missing: {FALLBACK_PROMPT_FILE}")
        return
    with open(FALLBACK_PROMPT_FILE, "r", encoding="utf-8") as f:
        fallback_prompt_template = f.read()

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
        process_movie_file(file_path, primary_prompt_template, fallback_prompt_template)

    print("\n✅ All highlighting completed successfully.")


if __name__ == "__main__":
    main()
