#!/usr/bin/env python3
"""
01-C_search-gemini.py
Secondary search script utilizing Google Gemini's native web search grounding.
Runs strictly for movies >= 4 days post-release that already have a pipeline log.
Targets publishers where standard search failed (PENDING).
Configured for Standard Flash models using Chat Sessions (AFC support).
"""

import builtins
import json
import os
import sys
import time
import re
import requests
from datetime import datetime
from urllib.parse import urlparse

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
PUBLISHERS_FILE = os.path.join(BASE_DIR, "publishers.json")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
PROMPT_FILE = os.path.join(PROMPTS_DIR, "gemini_web_search.txt")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("[FATAL ERROR] GEMINI_API_KEY environment variable is not set.")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

# LIVE WEB SEARCH REQUIRES STANDARD FLASH MODELS.
MODEL_CONFIG = [
    {"name": "gemini-3.8-flash", "priority": 1, "enabled": True},
    {"name": "gemini-3.7-flash", "priority": 2, "enabled": True},
    {"name": "gemini-3.5-flash", "priority": 3, "enabled": True}
]

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def get_domain(url):
    """Extracts the base domain from a URL"""
    if not url: return ""
    netloc = urlparse(url).netloc
    return netloc.replace("www.", "")

def resolve_redirect(url):
    """Unmasks Google Grounding redirect URLs to extract the canonical publisher URL."""
    if not url:
        return url
    
    if "vertexaisearch.cloud.google.com" in url or "google.com/url" in url:
        print(f"      [RESOLVE] Unmasking Google redirect URL...")
        try:
            # First attempt: fast HEAD request
            r = requests.head(url, allow_redirects=True, timeout=10)
            if r.status_code < 400 and r.url != url:
                print(f"      [RESOLVED] Canonical destination: {r.url}")
                return r.url
            
            # Second attempt: fallback GET request if server rejects HEAD
            r = requests.get(url, allow_redirects=True, timeout=10)
            print(f"      [RESOLVED] Canonical destination: {r.url}")
            return r.url
        except Exception as e:
            print(f"      [RESOLVE ERROR] Could not follow redirect: {e}")
            return url
    return url

def clean_json_response(raw_text):
    """Removes markdown code blocks and citation markers if the model wrapped the JSON."""
    clean_text = raw_text.strip()

    # Strip trailing search grounding citations (e.g., [1], [2])
    clean_text = re.sub(r'\[\d+\]', '', clean_text)

    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    clean_text = clean_text.strip()
    if not clean_text.startswith("{"):
        clean_text = "{" + clean_text
    return clean_text

def is_valid_result(data, expected_domain):
    """Validates the output according to strict rules. Allows FOUND and NOT_FOUND."""
    status = str(data.get("status", "")).strip().upper()

    valid_statuses = ["FOUND", "NOT_FOUND", "YES", "NO"]
    if status not in valid_statuses:
        return False

    if status in ["NOT_FOUND", "NO"]:
        return True

    url = str(data.get("url", "")).strip()
    title = str(data.get("title", "")).strip().lower()

    if not url or url.upper() == "NA" or expected_domain not in url:
        return False

    forbidden_words = ["trailer", "fan", "twitter"]
    if any(word in title for word in forbidden_words):
        return False

    return True

def run_gemini_search_with_fallback(client, prompt, models_config, config):
    """Handles routing the API call using a Chat Session to support Automatic Function Calling."""
    active_models = sorted(
        [m for m in models_config if m.get("enabled", True)],
        key=lambda x: x.get("priority", 999)
    )

    for model_info in active_models:
        model_name = model_info["name"]
        print(f"      [Attempting Model: {model_name}]")
        try:
            chat = client.chats.create(
                model=model_name,
                config=config
            )
            response = chat.send_message(prompt)

            if not getattr(response, "candidates", None) or not response.candidates:
                print(f"      [DEBUG ERROR] API call succeeded, but model returned candidates=None.")
                print(f"      [DEBUG RAW PAYLOAD]: {response}")
            else:
                try:
                    text_val = response.text
                    if text_val and text_val.strip():
                        print(f"      [LLM API RAW OUTPUT]:\n{text_val.strip()}")
                        return text_val
                except ValueError as ve:
                    print(f"      [DEBUG ERROR] SDK failed to parse response as text. {ve}")
                    print(f"      [DEBUG RAW PAYLOAD]: {response}")

        except errors.APIError as e:
            print(f"      [API Error on {model_name}]: {e}")
        except Exception as e:
            print(f"      [Unexpected Error on {model_name}]: {e}")

        print("      [Waiting 5 seconds before model fallback attempt...]")
        time.sleep(5)

    return None

# -----------------------------------------------------------------------------
# Main Execution Logic
# -----------------------------------------------------------------------------
def main():
    print("=" * 80)
    print(" 01-C: GEMINI WEB SEARCH RECOVERY (STANDARD FLASH)")
    print("=" * 80)

    if not os.path.exists(PROMPT_FILE):
        print(f"[FATAL ERROR] Prompt file missing: {PROMPT_FILE}")
        sys.exit(1)

    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL ERROR] {PUBLISHERS_FILE} not found.")
        sys.exit(1)

    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        publishers_data = json.load(f)

    pub_domain_map = {}
    for p in publishers_data:
        pub_domain_map[p["id"]] = get_domain(p.get("url", ""))

    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL ERROR] {MOVIES_FILE} not found.")
        sys.exit(1)

    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        movies_data = json.load(f)
    active_movies = movies_data.get("movies", [])

    grounding_tool = types.Tool(
        google_search=types.GoogleSearch()
    )

    gemini_config = types.GenerateContentConfig(
        tools=[grounding_tool],
        temperature=0.1
    )

    today = datetime.now().date()

    for movie in active_movies:
        movie_name = movie.get("name")
        slug = movie.get("slug")
        release_date_str = movie.get("date")

        print(f"\n[EVALUATING] {movie_name} ({slug})")

        try:
            release_date = datetime.strptime(release_date_str, "%Y-%m-%d").date()
            days_since = (today - release_date).days
            if days_since < 4:
                print(f"  -> Skipping: Only {days_since} days since release (requires >= 4).")
                continue
        except Exception as e:
            print(f"  -> Skipping: Invalid date format '{release_date_str}'")
            continue

        pipeline_dir = os.path.join(LOGS_DIR, f"logs_{slug}", f"pipeline_{slug}")
        if not os.path.exists(pipeline_dir) or not any(f.endswith(".txt") for f in os.listdir(pipeline_dir)):
            print(f"  -> Skipping: No pipeline execution logs found in {pipeline_dir}.")
            continue

        reviews_path = os.path.join(REVIEWS_DIR, f"reviews_{slug}.json")
        ai_logs_path = os.path.join(LOGS_DIR, f"logs_{slug}", "ai_processing_logs.json")
        script_log_path = os.path.join(LOGS_DIR, f"logs_{slug}", "01-C_search-gemini.json")

        if not os.path.exists(reviews_path) or not os.path.exists(ai_logs_path):
            print(f"  -> Error: Missing reviews or ai_logs file. Skipping.")
            continue

        with open(reviews_path, "r", encoding="utf-8") as f:
            rdata = json.load(f)

        with open(ai_logs_path, "r", encoding="utf-8") as f:
            ai_logs = json.load(f)

        data_changed = False
        ai_logs_changed = False
        searches_attempted = 0
        success_count = 0

        for pub in rdata.get("publishers", []):
            pub_id = pub.get("publisher_id")
            pub_name = pub.get("publisher_name")
            review_url = str(pub.get("review_url", "")).strip().upper()

            ai_status = ai_logs.get(pub_id, {}).get("01-C_search-gemini", "NOT_FOUND")

            if review_url == "PENDING" and ai_status == "PENDING":
                target_domain = pub_domain_map.get(pub_id, "")
                if not target_domain:
                    print(f"  -> Warning: No domain known for {pub_name}. Skipping.")
                    continue

                print(f"  -> [GEMINI SEARCH] Querying for {pub_name}...")
                searches_attempted += 1

                prompt = prompt_template.replace("{MOVIE_TITLE}", movie_name).replace("{PUBLISHER_URL}", target_domain)

                raw_response = run_gemini_search_with_fallback(client, prompt, MODEL_CONFIG, gemini_config)

                if pub_id not in ai_logs:
                    ai_logs[pub_id] = {}

                if raw_response:
                    try:
                        raw_json = clean_json_response(raw_response)
                        result = json.loads(raw_json)

                        # RESOLVE REDIRECT PRIOR TO DOMAIN VALIDATION
                        if "url" in result and str(result["url"]).strip().upper() != "NA":
                            result["url"] = resolve_redirect(str(result["url"]).strip())

                        if is_valid_result(result, target_domain):
                            ai_logs[pub_id]["01-C_search-gemini"] = "PROCESSED"
                            status = str(result.get("status", "")).strip().upper()

                            if status in ["FOUND", "YES"]:
                                print(f"     [SUCCESS] Valid URL Found: {result['url']}")
                                pub["review_url"] = result["url"]
                                pub["search_status"] = "SUCCESS"
                                pub["review_source"] = "gemini"
                                pub["review_title"] = result.get("title", "PENDING")
                                pub["article_title"] = result.get("title", "PENDING")
                                success_count += 1
                            else:
                                print(f"     [NOT FOUND] Gemini confirmed no review exists on domain.")
                        else:
                            print(f"     [INVALID] Output failed strict validation checks. Marking FAILED to retry next time.")
                            print(f"     [DEBUG RAW PARSED JSON]: {raw_json}")
                            ai_logs[pub_id]["01-C_search-gemini"] = "FAILED"

                    except Exception as e:
                        print(f"     [JSON/VALIDATION ERROR] Failed to parse output: {str(e)}")
                        ai_logs[pub_id]["01-C_search-gemini"] = "FAILED"
                else:
                    print(f"     [API FAILURE] Models failed or returned empty payload. Leaving as PENDING.")
                    time.sleep(15)
                    continue

                data_changed = True
                ai_logs_changed = True

                time.sleep(15)

        if data_changed:
            with open(reviews_path, "w", encoding="utf-8") as f:
                json.dump(rdata, f, indent=4, ensure_ascii=False)
            print(f"  -> Saved updates to reviews_{slug}.json")

        if ai_logs_changed:
            with open(ai_logs_path, "w", encoding="utf-8") as f:
                json.dump(ai_logs, f, indent=4, ensure_ascii=False)

        if searches_attempted > 0:
            script_history = {}
            if os.path.exists(script_log_path) and os.path.getsize(script_log_path) > 0:
                try:
                    with open(script_log_path, "r", encoding="utf-8") as f:
                        script_history = json.load(f)
                except Exception:
                    pass

            timestamp = datetime.now().astimezone().isoformat()
            script_history[timestamp] = {
                "attempts": searches_attempted,
                "urls_found": success_count,
                "urls_not_found_or_failed": searches_attempted - success_count
            }

            with open(script_log_path, "w", encoding="utf-8") as f:
                json.dump(script_history, f, indent=4, ensure_ascii=False)

    print("\n[COMPLETE] 01-C Gemini Search iteration finished.")

if __name__ == "__main__":
    main()
