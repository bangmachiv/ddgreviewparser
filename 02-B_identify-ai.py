#!/usr/bin/env python3
"""
02-B_identify-ai.py
Semantic evaluation script utilizing Google Gemini text models.
Reads search candidates (is_review == 'TBD') from Step 1 (DDGS / Tavily),
filters out previously rejected titles/URLs, evaluates fresh candidates
semantically to identify official editorial reviews, applies a deterministic
post-check blocklist on AI matches, enforces the 2-state is_review invariant
('Y-AI' / 'Y-DETERMINISTIC' + all others 'N', or all 'N') in searches_<slug>.json,
and updates reviews_<slug>.json.
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

# Fallback Cascade: Free Tier Flash Lite models
MODEL_CONFIG = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite"
]

# Deterministic post-check blocklist to veto non-editorial AI false positives
POST_CHECK_BLOCKLIST = [
    "twitter review", "x review", "x reacts",
    "public review", "audience review", "user review", "user reviews",
    "public reaction", "audience reaction", "fans react",
    "early reactions", "first reactions",
    "पब्लिक रिव्यू", "ट्विटर रिव्यू",
    "trailer review", "teaser review", "music review", "album review",
    "first look", "फर्स्ट लुक",
    "ending explained", "plot explained",
    "live updates", "live blog",
    "release date", "ott release", "where to watch", "showtimes",
    "रिलीज डेट", "ओटीटी",
    "exclusive interview"
]

# Load threshold from central config (supports new 02-B key with 02-C fallback)
MIN_CONFIDENCE_THRESHOLD = 95
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            script_config = config_data.get("02-B_identify-ai") or config_data.get("02-C_identify-ai", {})
            MIN_CONFIDENCE_THRESHOLD = script_config.get("AI_MIN_CONFIDENCE_THRESHOLD", 95)
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

def create_reference_string(text):
    """Strips all spaces and non-alphanumeric characters, returning lowercase string."""
    if not text:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', str(text)).lower()

def get_blocked_reason(title: str, url: str):
    """Returns the matched blocklist phrase if the candidate is a known non-editorial false positive."""
    combined = f"{title} {url}".lower()
    padded = f" {re.sub(r'[^\w\s]', ' ', combined)} "
    for phrase in POST_CHECK_BLOCKLIST:
        if f" {phrase} " in padded:
            return phrase
    return None

def reconcile_publisher_bucket(candidates, confirmed_url, marker):
    """
    Enforces the 2-state invariant on a publisher's search results:
    - If confirmed_url is provided: marks that URL with marker ('Y-DETERMINISTIC' or 'Y-AI')
      and marks all other URLs as 'N'.
    - Returns True if any item's is_review field was modified.
    """
    changed = False
    target_url = str(confirmed_url or "").strip()
    for c in candidates:
        if not isinstance(c, dict):
            continue
        c_url = str(c.get("url") or "").strip()
        desired_state = marker if (target_url and c_url == target_url) else "N"
        if c.get("is_review") != desired_state:
            c["is_review"] = desired_state
            changed = True
    return changed

def run_gemini_evaluation(client, prompt):
    """Executes text generation call with fallback cascade and 5 RPM timegaps."""
    for model_name in MODEL_CONFIG:
        print(f"      [RATE LIMIT] Sleeping 13 seconds to respect 5 RPM limit...")
        time.sleep(13)
        print(f"      [Attempting Model: {model_name}]")

        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1)
            )

            if not getattr(response, "candidates", None) or not response.candidates:
                print(f"      [DEBUG ERROR] API call succeeded on {model_name}, but candidates=None.")
                continue  # Trigger fallback

            text_val = response.text
            if text_val and text_val.strip():
                print(f"      [LLM API RAW OUTPUT ({model_name})]:\n{text_val.strip()}")
                return text_val

        except errors.APIError as e:
            print(f"      [API Error on {model_name}]: {e}")
        except Exception as e:
            print(f"      [Unexpected Error on {model_name}]: {e}")

    return None

def print_summary_table(global_stats):
    """Prints a clean markdown-style summary table to the console."""
    if not global_stats:
        return

    print("\n" + "=" * 80)
    print(" 02-B: EXECUTION SUMMARY TABLE")
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
    print(f" 02-B: GEMINI SEMANTIC IDENTIFICATION (Threshold: {MIN_CONFIDENCE_THRESHOLD}%)")
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

        # Pre-calculate the compressed movie string for baseline relevance checking
        movie_ref_string = create_reference_string(movie_name)

        print(f"\n[EVALUATING] {movie_name} ({slug})")

        reviews_path = os.path.join(REVIEWS_DIR, f"reviews_{slug}.json")
        searches_path = os.path.join(SEARCHES_DIR, f"searches_{slug}.json")
        negative_searches_path = os.path.join(SEARCHES_DIR, f"negative_searches_{slug}.json")

        movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{slug}")
        ai_logs_path = os.path.join(movie_logs_dir, "ai_processing_logs.json")
        script_log_path = os.path.join(movie_logs_dir, "02-B_identify-ai.json")

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
        searches_changed = False
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
            raw_review_url = str(pub.get("review_url", "")).strip()
            review_url_upper = raw_review_url.upper()
            sc = pub.get("search_count", 0)
            candidates = search_results_map.get(pub_id, [])

            # Already confirmed (by 02-A deterministic or prior 02-B AI):
            # Enforce 1 Y-(marker) + all others N in searches_<slug>.json
            if review_url_upper not in ["PENDING", "FAILED", "NA", ""]:
                if candidates:
                    classified_by = str(pub.get("classified_by") or "").strip().upper()
                    marker = "Y-DETERMINISTIC" if classified_by == "SCRIPT" else "Y-AI"
                    if reconcile_publisher_bucket(candidates, raw_review_url, marker):
                        searches_changed = True
                continue

            # Execution Gate: Unresolved review_url with available search results
            if sc > 0 and candidates:
                rejected_titles = set(negative_data["publishers"].get(pub_id, []))

                compact_candidates = []
                numbered_candidate_lines = []
                idx = 1
                filtered_out_count = 0

                print(f"\n------")
                print(f"Starting for {pub_name}\n")

                for c in candidates:
                    if not isinstance(c, dict):
                        continue

                    # Gate on is_review state machine (skip already classified Y/N URLs)
                    if str(c.get("is_review", "TBD")).strip().upper() != "TBD":
                        continue

                    title = str(c.get("title", "")).strip()
                    url = str(c.get("url", "")).strip()

                    # Filter 1: Check negative cache
                    if title in rejected_titles:
                        c["is_review"] = "N"
                        searches_changed = True
                        continue

                    # Filter 2: Baseline relevance check (check both title & URL slug so Hindi titles aren't dropped)
                    title_ref_string = create_reference_string(title)
                    url_ref_string = create_reference_string(url)
                    if movie_ref_string not in title_ref_string and movie_ref_string not in url_ref_string:
                        filtered_out_count += 1
                        c["is_review"] = "N"
                        searches_changed = True

                        if pub_id not in negative_data["publishers"]:
                            negative_data["publishers"][pub_id] = []
                        if title and title not in negative_data["publishers"][pub_id]:
                            negative_data["publishers"][pub_id].append(title)
                            negative_data_changed = True

                        continue

                    compact_candidates.append({
                        "title": title,
                        "url": url,
                        "match_type": str(c.get("match_type") or "gemini_semantic").strip(),
                        "raw_ref": c
                    })
                    numbered_candidate_lines.append(f"{idx}. {title}")

                    print(f"[{get_ordinal(idx)} Title] {title}")
                    idx += 1

                if filtered_out_count > 0:
                    print(f"  -> [FILTERED] Dropped {filtered_out_count} candidate(s) missing movie name reference string.")

                if not compact_candidates:
                    print(f"  -> [SKIP] All available candidates were previously evaluated, rejected, or filtered out.")
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
                        break
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
                            ai_logs[pub_id]["02-B_classify-ai"] = current_iso_time
                            ai_logs_changed = True
                            print(f"     [LOGGED] Recorded timestamp in ai_processing_logs: {current_iso_time}")

                            admissible_matches = [
                                c for c in valid_parsed_candidates if c["confidence"] >= MIN_CONFIDENCE_THRESHOLD
                            ]

                            matched_url = None
                            matched_title = None

                            if admissible_matches:
                                admissible_matches.sort(key=lambda x: x["confidence"], reverse=True)
                                chosen_match = None

                                for cand_match in admissible_matches:
                                    cand_sn = cand_match["serial_number"]
                                    cand_conf = cand_match["confidence"]
                                    cand_item = compact_candidates[cand_sn - 1]
                                    blocked_reason = get_blocked_reason(cand_item["title"], cand_item["url"])
                                    if blocked_reason:
                                        print(f"     [POST-CHECK BLOCKED] Serial #{cand_sn} ({cand_conf}%) rejected due to '{blocked_reason}': {cand_item['title']}")
                                        continue
                                    chosen_match = (cand_sn, cand_conf, cand_item)
                                    break

                                if chosen_match:
                                    best_sn, best_conf, matched_item = chosen_match
                                    matched_url = matched_item["url"]
                                    matched_title = matched_item["title"]
                                    matched_source = matched_item["match_type"]

                                    print(f"     [SUCCESS] Admissible match (Confidence: {best_conf}% >= {MIN_CONFIDENCE_THRESHOLD}%): Serial #{best_sn}")
                                    print(f"     [URL]: {matched_url}")

                                    pub["review_url"] = matched_url
                                    pub["search_status"] = "SUCCESS"
                                    pub["review_source"] = matched_source
                                    pub["review_title"] = matched_title
                                    pub["classified_by"] = "AI"

                                    # Unlock Step 3/4 content extraction & adjudication for AI-classified reviews
                                    if pub.get("webpage_content_extraction") in [None, "", "NOT_NEEDED"]:
                                        pub["webpage_content_extraction"] = "PENDING"
                                    if pub.get("webpage_content_adjudication") in [None, "", "NOT_NEEDED"]:
                                        pub["webpage_content_adjudication"] = "PENDING"

                                    # Enforce 1 'Y-AI' + all others 'N' across the entire publisher bucket
                                    if reconcile_publisher_bucket(candidates, matched_url, "Y-AI"):
                                        searches_changed = True

                                    data_changed = True
                                    movie_stats["found"] += 1
                                else:
                                    print(f"     [NOT ADMISSIBLE] All AI matches were blocked by deterministic post-check. Remaining PENDING.")
                                    if reconcile_publisher_bucket(candidates, None, "N"):
                                        searches_changed = True
                                    movie_stats["not_found"] += 1
                            else:
                                print(f"     [NOT ADMISSIBLE] No candidate met confidence threshold >= {MIN_CONFIDENCE_THRESHOLD}% (or returned empty). Remaining PENDING.")
                                if reconcile_publisher_bucket(candidates, None, "N"):
                                    searches_changed = True
                                movie_stats["not_found"] += 1

                            # Cache all non-winning evaluated titles in negative_searches_<slug>.json
                            newly_rejected_titles = [
                                cand["title"] for cand in compact_candidates
                                if cand["url"] != matched_url and cand["title"]
                            ]

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
            print(f"  -> Saved execution history to 02-B_identify-ai.json")

        if data_changed:
            with open(reviews_path, "w", encoding="utf-8") as f:
                json.dump(rdata, f, indent=4, ensure_ascii=False)
            print(f"  -> Saved updates to reviews_{slug}.json")

        if searches_changed:
            with open(searches_path, "w", encoding="utf-8") as f:
                json.dump(sdata, f, indent=4, ensure_ascii=False)
            print(f"  -> Saved is_review updates to searches_{slug}.json")

        if ai_logs_changed:
            with open(ai_logs_path, "w", encoding="utf-8") as f:
                json.dump(ai_logs, f, indent=4, ensure_ascii=False)
            print(f"  -> Saved updates to ai_processing_logs.json")

        if negative_data_changed:
            with open(negative_searches_path, "w", encoding="utf-8") as f:
                json.dump(negative_data, f, indent=4, ensure_ascii=False)

    print_summary_table(global_execution_stats)
    print("\n[COMPLETE] 02-B Gemini Semantic Identification finished.")

if __name__ == "__main__":
    main()
