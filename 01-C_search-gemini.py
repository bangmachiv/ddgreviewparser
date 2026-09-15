#!/usr/bin/env python3
"""
01-C_search-gemini.py
Secondary search script utilizing Google Gemini's native web search grounding.
Runs strictly for movies >= 4 days post-release that already have a pipeline log.
Targets publishers where standard search failed (PENDING).
"""

import json
import os
import sys
import time
import re
from datetime import datetime
from urllib.parse import urlparse

try:
    from google import genai
    from google.genai import types
    from google.genai import errors
except ImportError:
    print("[FATAL ERROR] google-genai package is missing. Run: pip install google-genai")
    sys.exit(1)

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

# Define Fallback Models
MODEL_CONFIG = [
    {"name": "gemini-2.5-flash", "priority": 1, "enabled": True},
    {"name": "gemini-2.5-flash-lite", "priority": 2, "enabled": True},
    {"name": "gemini-1.5-flash", "priority": 3, "enabled": True}
]

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def get_domain(url):
    """Extracts the base domain from a URL (e.g., https://www.koimoi.com -> koimoi.com)"""
    if not url: return ""
    netloc = urlparse(url).netloc
    return netloc.replace("www.", "")

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

def is_valid_result(data, expected_domain):
    """Validates the output according to strict rules. Allows FOUND and NOT_FOUND."""
    status = str(data.get("status", "")).strip().upper()
    
    # Check if the AI returned a definitive valid status
    valid_statuses = ["FOUND", "NOT_FOUND", "YES", "NO"]
    if status not in valid_statuses:
        return False
        
    # If the AI definitively couldn't find it, the JSON structure is still valid
    if status in ["NOT_FOUND", "NO"]:
        return True
    
    # If the AI claims it FOUND it, we must strictly validate the URL and Title
    url = str(data.get("url", "")).strip()
    title = str(data.get("title", "")).strip().lower()

    # 1. URL must not be empty, NA, and MUST contain the expected domain
    if not url or url.upper() == "NA" or expected_domain not in url:
        return False
    
    # 2. Title must not contain forbidden words representing wrong article types
    forbidden_words = ["trailer", "fan", "twitter"]
    if any(word in title for word in forbidden_words):
        return False
    
    return True

def run_gemini_search_with_fallback(client, prompt, models_config, config):
    """Handles routing the API call through the fallback hierarchy."""
    active_models = sorted(
        [m for m in models_config if m.get("enabled", True)],
        key=lambda x: x.get("priority", 999)
    )

    for model_info in active_models:
        model_name = model_info["name"]
        print(f"      [Attempting Model: {model_name}]")
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            return response.text
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
    print(" 01-C: GEMINI WEB SEARCH RECOVERY")
    print("=" * 80)

    # 1. Load Prompt Template
    if not os.path.exists(PROMPT_FILE):
        print(f"[FATAL ERROR] Prompt file missing: {PROMPT_FILE}")
        sys.exit(1)
    
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        prompt_template = f.read()

    # 2. Load Publishers Map
    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL ERROR] {PUBLISHERS_FILE} not found.")
        sys.exit(1)

    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        publishers_data = json.load(f)
        
    pub_domain_map = {}
    for p in publishers_data:
        pub_domain_map[p["id"]] = get_domain(p.get("url", ""))

    # 3. Load Movies
    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL ERROR] {MOVIES_FILE} not found.")
        sys.exit(1)

    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        movies_data = json.load(f)
    active_movies = movies_data.get("movies", [])

    # Configure Gemini with Search Grounding
    grounding_tool = types.Tool(
        google_search=types.GoogleSearch()
    )
    gemini_config = types.GenerateContentConfig(
        tools=[grounding_tool], 
        response_mime_type="application/json",
        temperature=0.1
    )

    today = datetime.now().date()

    for movie in active_movies:
        movie_name = movie.get("name")
        slug = movie.get("slug")
        release_date_str = movie.get("date")

        print(f"\n[EVALUATING] {movie_name} ({slug})")

        # Condition 1: Must be >= 4 days post-release
        try:
            release_date = datetime.strptime(release_date_str, "%Y-%m-%d").date()
            days_since = (today - release_date).days
            if days_since < 4:
                print(f"  -> Skipping: Only {days_since} days since release (requires >= 4).")
                continue
        except Exception as e:
            print(f"  -> Skipping: Invalid date format '{release_date_str}'")
            continue

        # Condition 2: Must have actual run of pipeline (pipeline log exists)
        pipeline_dir = os.path.join(LOGS_DIR, f"logs_{slug}", f"pipeline_{slug}")
        if not os.path.exists(pipeline_dir) or not any(f.endswith(".txt") for f in os.listdir(pipeline_dir)):
            print(f"  -> Skipping: No pipeline execution logs found in {pipeline_dir}.")
            continue

        # Setup paths for this movie
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

        # Iterate Publishers
        for pub in rdata.get("publishers", []):
            pub_id = pub.get("publisher_id")
            pub_name = pub.get("publisher_name")
            review_url = str(pub.get("review_url", "")).strip().upper()
            
            # Condition 3 & 4: review_url must be PENDING and 01-C tracking must be PENDING
            ai_status = ai_logs.get(pub_id, {}).get("01-C_search-gemini", "NOT_FOUND")
            
            if review_url == "PENDING" and ai_status == "PENDING":
                target_domain = pub_domain_map.get(pub_id, "")
                if not target_domain:
                    print(f"  -> Warning: No domain known for {pub_name}. Skipping.")
                    continue

                print(f"  -> [GEMINI SEARCH] Querying for {pub_name}...")
                searches_attempted += 1

                # Construct Prompt dynamically
                prompt = prompt_template.replace("{MOVIE_TITLE}", movie_name).replace("{PUBLISHER_URL}", target_domain)

                # Execute with Model Fallbacks
                raw_response = run_gemini_search_with_fallback(client, prompt, MODEL_CONFIG, gemini_config)

                if pub_id not in ai_logs:
                    ai_logs[pub_id] = {}

                if raw_response:
                    try:
                        raw_json = clean_json_response(raw_response)
                        result = json.loads(raw_json)

                        # Validate Output
                        if is_valid_result(result, target_domain):
                            # Regardless of FOUND or NOT_FOUND, the AI successfully completed its task
                            ai_logs[pub_id]["01-C_search-gemini"] = "PROCESSED"
                            
                            status = str(result.get("status", "")).strip().upper()
                            
                            if status in ["FOUND", "YES"]:
                                print(f"     [SUCCESS] Valid URL Found: {result['url']}")
                                pub["review_url"] = result["url"]
                                pub["search_status"] = "SUCCESS"
                                pub["review_source"] = "gemini_search"
                                pub["review_title"] = result.get("title", "PENDING")
                                success_count += 1
                            else:
                                print(f"     [NOT FOUND] Gemini exhausted searches but confirmed no review exists yet.")
                        else:
                            print(f"     [INVALID] Output failed strict validation checks. Marking FAILED to retry next time.")
                            ai_logs[pub_id]["01-C_search-gemini"] = "FAILED"
                            
                    except Exception as e:
                        print(f"     [JSON/VALIDATION ERROR] Failed to parse output: {str(e)}")
                        ai_logs[pub_id]["01-C_search-gemini"] = "FAILED"
                else:
                    print(f"     [API FAILURE] All models failed. Leaving as PENDING.")
                    # We leave it as PENDING because it was a hard API crash (e.g., rate limit), not a search evaluation failure
                    time.sleep(15)
                    continue

                data_changed = True
                ai_logs_changed = True

                # Required 15-second delay to prevent rate-limiting on iterative searches
                time.sleep(15)

        # Save data if modifications were made
        if data_changed:
            with open(reviews_path, "w", encoding="utf-8") as f:
                json.dump(rdata, f, indent=4, ensure_ascii=False)
            print(f"  -> Saved updates to reviews_{slug}.json")
            
        if ai_logs_changed:
            with open(ai_logs_path, "w", encoding="utf-8") as f:
                json.dump(ai_logs, f, indent=4, ensure_ascii=False)

        # Self-Logging script run
        if searches_attempted > 0:
            script_history = {}
            if os.path.exists(script_log_path) and os.path.getsize(script_log_path) > 0:
                try:
                    with open(script_log_path, "r", encoding="utf-8") as f:
                        script_history = json.load(f)
                except:
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
