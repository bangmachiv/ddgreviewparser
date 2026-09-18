#!/usr/bin/env python3
"""
02-C_identify-ai.py
Semantic evaluation script utilizing Google Gemini text models.
Reads DDGS search candidates from Step 1, filters out previously rejected titles, 
and evaluates fresh titles semantically to identify official editorial reviews.
Executes purely as a text prompt (Zero Search API costs).
Features zero-delay fallback cascade, 2-attempt retries, real-time logs, dedicated history JSON, and terminal summary tables.
"""

import builtins
import json
import os
import sys
import time
import re
from datetime import datetime

try:
    from google import genai
    from google.genai import types
    from google.genai import errors
except ImportError:
    print("[FATAL ERROR] google-genai package is missing. Run: pip install google-genai")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Global Print Override for Real-Time CI/CD Streaming
# ---------------------------------------------------------------------------
def print(*args, **kwargs):
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

# -----------------------------------------------------------------------------
# Configuration & Absolute Pathing
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
SEARCHES_DIR = os.path.join(BASE_DIR, "data", "searches")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
PROMPT_FILE = os.path.join(PROMPTS_DIR, "identify_article_title.txt")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("[FATAL ERROR] GEMINI_API_KEY environment variable is not set.")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

# Fallback Cascade: 4 Flash models from latest to oldest
MODEL_CONFIG = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash"
]

# Load threshold from central config
MIN_CONFIDENCE_THRESHOLD = 95
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            MIN_CONFIDENCE_THRESHOLD = config_data.get("AI_MIN_CONFIDENCE_THRESHOLD", 95)
    except Exception as e:
        print(f"[WARNING] Could not load config.json, defaulting to {MIN_CONFIDENCE_THRESHOLD}: {e}")

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def get_ordinal(n):
    """Returns ordinal string (1st, 2nd, 3rd) for formatted printing."""
    if 11 <= (n % 100) <= 13:
        return str(n) + "th"
    return str(n) + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")

def clean_json_response(raw_text):
    """Removes markdown code blocks if the model wrapped the JSON."""
    clean_text = raw_text.strip()
    clean_text = re.sub(r'\[\d+\]', '', clean_text)

    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    return clean_text.strip()

def run_gemini_evaluation(client, prompt):
    """Executes text generation call with instant fallback cascade."""
    for model_name in MODEL_CONFIG:
        print(f"      [Attempting Model: {model_name}]")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1)
            )

            if not getattr(response, "candidates", None) or not response.candidates:
                print(f"      [DEBUG ERROR] API call succeeded on {model_name}, but candidates=None.")
                continue # Instantly trigger fallback

            text_val = response.text
            if text_val and text_val.strip():
                print(f"      [LLM API RAW OUTPUT ({model_name})]:\n{text_val.strip()}")
                return text_val

        except errors.APIError as e:
            print(f"      [API Error on {model_name}]: {e}")
        except Exception as e:
            print(f"      [Unexpected Error on {model_name}]: {e}")

    # If all models in the cascade fail
    return None

def print_summary_table(global_stats):
    """Prints a clean markdown-style summary table to the console."""
    if not global_stats:
        return

    print("\n" + "=" * 80)
    print(" 02-C: EXECUTION SUMMARY TABLE")
    print("=" * 80)
    print(f"| {'Movie Slug':<30} | {'Pubs Eval':<10} | {'Matches':<8} | {'Rejected':<10} |")
    print("-" * 71)
    for stat in global_stats:
        print(f"| {stat['slug']:<30} | {stat['evaluated']:<10} | {stat['found']:<8} | {stat['not_found']:<10} |")
    print("-" * 71 + "\n")

# -----------------------------------------------------------------------------
# Main Execution Logic
# -----------------------------------------------------------------------------
def main():
    print("=" * 80)
    print(f" 02-C: GEMINI SEMANTIC IDENTIFICATION (Threshold: {MIN_CONFIDENCE_THRESHOLD}%)")
    print("=" * 80)

    if not os.path.exists(PROMPT_FILE):
        print(f"[FATAL ERROR] Prompt file missing: {PROMPT_FILE}")
        sys.exit(1)

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL ERROR] {MOVIES_FILE} not found.")
        sys.exit(1)

    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        movies_data = json.load(f)
    active_movies = movies_data.get("movies", [])

    global_execution_stats = []

    for movie in active_movies:
        movie_name = movie.get("name")
        slug = movie.get("slug")

        print(f"\n[EVALUATING] {movie_name} ({slug})")

        reviews_path = os.path.join(REVIEWS_DIR, f"reviews_{slug}.json")
        searches_path = os.path.join(SEARCHES_DIR, f"searches_{slug}.json")
        negative_searches_path = os.path.join(SEARCHES_DIR, f"negative_searches_{slug}.json")

        movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{slug}")
        ai_logs_path = os.path.join(movie_logs_dir, "ai_processing_logs.json")
        script_log_path = os.path.join(movie_logs_dir, "02-C_identify-ai.json")

        if not os.path.exists(reviews_path) or not os.path.exists(searches_path):
            print(f"  -> Skipping: Missing reviews or searches JSON file.")
            continue

        if not os.path.exists(ai_logs_path):
            os.makedirs(os.path.dirname(ai_logs_path), exist_ok=True)
            ai_logs = {}
        else:
            with open(ai_logs_path, "r", encoding="utf-8") as f:
                try:
                    ai_logs = json.load(f)
                except json.JSONDecodeError:
                    ai_logs = {}

        if os.path.exists(negative_searches_path):
            with open(negative_searches_path, "r", encoding="utf-8") as f:
                try:
                    negative_data = json.load(f)
                except json.JSONDecodeError:
                    negative_data = {"movie": {"name": movie_name, "slug": slug}, "publishers": {}}
        else:
            negative_data = {"movie": {"name": movie_name, "slug": slug}, "publishers": {}}

        with open(reviews_path, "r", encoding="utf-8") as f:
            rdata = json.load(f)

        with open(searches_path, "r", encoding="utf-8") as f:
            sdata = json.load(f)

        search_results_map = {pub["publisher_id"]: pub.get("results", []) for pub in sdata.get("publishers", [])}

        data_changed = False
        ai_logs_changed = False
        negative_data_changed = False

        movie_stats = {
            "slug": slug,
            "evaluated": 0,
            "found": 0,
            "not_found": 0
        }

        for pub in rdata.get("publishers", []):
            pub_id = pub.get("publisher_id")
            pub_name = pub.get("publisher_name")
            review_url = str(pub.get("review_url", "")).strip().upper()

            ai_timestamp = ai_logs.get(pub_id, {}).get("02-C_identify-ai")

            if review_url == "PENDING" and not ai_timestamp:
                candidates = search_results_map.get(pub_id, [])

                if not candidates:
                    continue

                rejected_titles = set(negative_data["publishers"].get(pub_id, []))

                compact_candidates = []
                numbered_candidate_lines = []
                idx = 1
                
                print(f"\n------")
                print(f"Starting for {pub_name}\n")

                for c in candidates:
                    title = c.get("title", "").strip()
                    url = c.get("url", "").strip()

                    if title in rejected_titles:
                        continue

                    compact_candidates.append({"title": title, "url": url})
                    numbered_candidate_lines.append(f"{idx}. {title}")
                    
                    print(f"[{get_ordinal(idx)} Title] {title}")
                    idx += 1

                if not compact_candidates:
                    print(f"  -> [SKIP] All available candidates were previously rejected.")
                    continue

                print(f"\n  -> [GEMINI EVAL] Analyzing {len(compact_candidates)} fresh search candidates...")
                movie_stats["evaluated"] += 1

                numbered_list_str = "\n".join(numbered_candidate_lines)
                prompt = prompt_template.replace("{MOVIE_TITLE}", movie_name)\
                                        .replace("{NUMBERED_CANDIDATE_TITLES_LIST}", numbered_list_str)

                raw_response = None
                MAX_RETRIES = 2
                
                for attempt in range(1, MAX_RETRIES + 1):
                    raw_response = run_gemini_evaluation(client, prompt)
                    
                    if raw_response:
                        break # Success, break out of retry loop
                    else:
                        print(f"     [API FAILURE] All cascade models failed on attempt {attempt}.")
                        if attempt < MAX_RETRIES:
                            print(f"     [RETRYING] Waiting 2 seconds before attempt {attempt + 1}...")
                            time.sleep(2)

                if pub_id not in ai_logs:
                    ai_logs[pub_id] = {}

                if raw_response:
                    try:
                        raw_json = clean_json_response(raw_response)
                        parsed_payload = json.loads(raw_json)

                        is_valid_response = False
                        valid_parsed_candidates = []

                        if isinstance(parsed_payload, list):
                            if len(parsed_payload) == 0:
                                is_valid_response = True
                            else:
                                for item in parsed_payload:
                                    if isinstance(item, dict):
                                        sn = item.get("serial_number")
                                        conf = item.get("confidence")
                                        try:
                                            sn_int = int(sn)
                                            conf_int = int(conf)
                                            if 1 <= sn_int <= len(compact_candidates):
                                                valid_parsed_candidates.append({
                                                    "serial_number": sn_int,
                                                    "confidence": conf_int
                                                })
                                        except (ValueError, TypeError):
                                            continue

                                if len(valid_parsed_candidates) > 0:
                                    is_valid_response = True

                        elif isinstance(parsed_payload, dict):
                            status = str(parsed_payload.get("status", "")).strip().upper()
                            if status in ["NOT_FOUND", "NO"]:
                                is_valid_response = True
                            else:
                                sn = parsed_payload.get("serial_number")
                                conf = parsed_payload.get("confidence")
                                try:
                                    sn_int = int(sn)
                                    conf_int = int(conf)
                                    if 1 <= sn_int <= len(compact_candidates):
                                        valid_parsed_candidates.append({
                                            "serial_number": sn_int,
                                            "confidence": conf_int
                                        })
                                        is_valid_response = True
                                except (ValueError, TypeError):
                                    pass

                        if is_valid_response:
                            current_iso_time = datetime.now().astimezone().isoformat()
                            ai_logs[pub_id]["02-C_classify-ai"] = current_iso_time
                            ai_logs_changed = True
                            print(f"     [LOGGED] Recorded timestamp in ai_processing_logs: {current_iso_time}")

                            admissible_matches = [
                                c for c in valid_parsed_candidates if c["confidence"] >= MIN_CONFIDENCE_THRESHOLD
                            ]

                            matched_title = None

                            if admissible_matches:
                                admissible_matches.sort(key=lambda x: x["confidence"], reverse=True)
                                best_match = admissible_matches[0]
                                best_sn = best_match["serial_number"]
                                best_conf = best_match["confidence"]

                                matched_item = compact_candidates[best_sn - 1]
                                matched_url = matched_item["url"]
                                matched_title = matched_item["title"]

                                print(f"     [SUCCESS] Admissible match (Confidence: {best_conf}% >= {MIN_CONFIDENCE_THRESHOLD}%): Serial #{best_sn}")
                                print(f"     [URL]: {matched_url}")

                                pub["review_url"] = matched_url
                                pub["search_status"] = "SUCCESS"
                                pub["review_source"] = "gemini_semantic"
                                pub["review_title"] = matched_title
                                pub["article_title"] = matched_title
                                pub["classified_by"] = "AI"

                                data_changed = True
                                movie_stats["found"] += 1
                            else:
                                print(f"     [NOT ADMISSIBLE] No candidate met confidence threshold >= {MIN_CONFIDENCE_THRESHOLD}% (or returned empty). Remaining PENDING.")
                                movie_stats["not_found"] += 1

                            newly_rejected_titles = [c["title"] for c in compact_candidates if c["title"] != matched_title]

                            if newly_rejected_titles:
                                if pub_id not in negative_data["publishers"]:
                                    negative_data["publishers"][pub_id] = []

                                existing_negatives = set(negative_data["publishers"][pub_id])
                                for title in newly_rejected_titles:
                                    if title not in existing_negatives:
                                        negative_data["publishers"][pub_id].append(title)

                                negative_data_changed = True
                                print(f"     [NEGATIVE CACHE] Appended {len(newly_rejected_titles)} rejected title(s) to negative_searches_{slug}.json")

                        else:
                            print(f"     [INVALID OUTPUT] Model output did not contain a valid serial number or NOT_FOUND indicator. Timestamp NOT recorded.")

                    except Exception as e:
                        print(f"     [JSON ERROR] Failed to parse output as valid JSON: {str(e)}")
                        print(f"     [DEBUG RAW]: {raw_response}")
                else:
                    print(f"     [API FATAL] Publisher exhausted all retries. Moving to next publisher.")

        if movie_stats["evaluated"] > 0:
            global_execution_stats.append(movie_stats)

            script_history = {}
            if os.path.exists(script_log_path) and os.path.getsize(script_log_path) > 0:
                try:
                    with open(script_log_path, "r", encoding="utf-8") as f:
                        script_history = json.load(f)
                except Exception:
                    pass

            timestamp = datetime.now().astimezone().isoformat()
            script_history[timestamp] = {
                "publishers_evaluated": movie_stats["evaluated"],
                "matches_found": movie_stats["found"],
                "no_matches_found": movie_stats["not_found"]
            }

            with open(script_log_path, "w", encoding="utf-8") as f:
                json.dump(script_history, f, indent=4, ensure_ascii=False)
            print(f"  -> Saved execution history to 02-C_identify-ai.json")

        if data_changed:
            with open(reviews_path, "w", encoding="utf-8") as f:
                json.dump(rdata, f, indent=4, ensure_ascii=False)
            print(f"  -> Saved updates to reviews_{slug}.json")

        if ai_logs_changed:
            with open(ai_logs_path, "w", encoding="utf-8") as f:
                json.dump(ai_logs, f, indent=4, ensure_ascii=False)
            print(f"  -> Saved updates to ai_processing_logs.json")

        if negative_data_changed:
            with open(negative_searches_path, "w", encoding="utf-8") as f:
                json.dump(negative_data, f, indent=4, ensure_ascii=False)

    print_summary_table(global_execution_stats)
    print("\n[COMPLETE] 02-C Gemini Semantic Identification finished.")

if __name__ == "__main__":
    main()
