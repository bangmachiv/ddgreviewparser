import json
import os
import re
import time
import html
from google import genai
from google.genai import errors

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "find_title_highlight.txt")
LIVE_MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")

# ---------------------------------------------------------------------------
# Gemini API Setup & Fallback Models
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("[ERROR] GEMINI_API_KEY environment variable not found!")
    exit(1)

client = genai.Client(api_key=API_KEY)

MODEL_CONFIG = [
    {"name": "gemini-3.5-flash-lite", "priority": 1, "enabled": True},
    {"name": "gemini-3.5-flash", "priority": 2, "enabled": True},
    {"name": "gemini-3.6-flash", "priority": 3, "enabled": True}
]

# ---------------------------------------------------------------------------
# Validation & Formatting Logic
# ---------------------------------------------------------------------------
def clean_json_response(text):
    """Strips Markdown code blocks if present."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
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

def process_and_validate_highlight(clean_title, gemini_response_text):
    """
    Validates Gemini's response and injects asterisks around the first occurrence
    of valid emotion keywords.
    """
    if not gemini_response_text or not gemini_response_text.strip():
        print("      [FAIL] Gemini returned empty response.")
        return None

    try:
        raw_json = clean_json_response(gemini_response_text)
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

def fetch_highlights_with_fallback(movie_name, clean_title, prompt_template):
    prompt = prompt_template.replace("{movie_name}", movie_name).replace("{clean_title}", clean_title)
    
    active_models = sorted(
        [m for m in MODEL_CONFIG if m.get("enabled", True)],
        key=lambda x: x.get("priority", 999)
    )

    for model_info in active_models:
        model_name = model_info["name"]
        print(f"      [Attempting Model: {model_name}]")
        
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            
            if response and response.text:
                raw_text = response.text.strip()
                print(f"      [DEBUG Raw Gemini Response]: {raw_text}")
                
                # Check validation before accepting this model's response
                highlighted = process_and_validate_highlight(clean_title, raw_text)
                if highlighted:
                    return highlighted
                else:
                    print("      [Validation Failed for this model output, attempting fallback...]")
        except errors.APIError as e:
            print(f"      [API Error on {model_name}]: {e.message}")
        except Exception as e:
            print(f"      [Unexpected Error on {model_name}]: {e}")
            
        print("      [Waiting 3s before fallback model attempt...]")
        time.sleep(3)
        
    return None

def process_movie_file(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" HIGHLIGHTING TITLES FOR: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_name = data.get("movie", {}).get("name", "Unknown Movie")
    publishers = data.get("publishers", [])
    
    updated_file = False
    summary_counts = {
        "Skipped (No clean_title)": 0,
        "Skipped (Already highlighted)": 0,
        "Highlighted successfully": 0,
        "Discarded (Failed validation / Null)": 0
    }

    for pub in publishers:
        pub_id = pub.get("publisher_id", "Unknown")
        clean_title = pub.get("clean_title")
        existing_highlight = pub.get("clean_highlighted_title")

        if not clean_title or not str(clean_title).strip():
            summary_counts["Skipped (No clean_title)"] += 1
            continue
            
        if existing_highlight and str(existing_highlight).strip():
            summary_counts["Skipped (Already highlighted)"] += 1
            continue

        print(f"\n  [*] Processing [{pub_id}]")
        print(f"      Title: {clean_title}")

        highlighted_title = fetch_highlights_with_fallback(movie_name, clean_title, prompt_template)
        
        if highlighted_title:
            pub["clean_highlighted_title"] = highlighted_title
            print(f"      [SUCCESS] Saved: {highlighted_title}")
            summary_counts["Highlighted successfully"] += 1
            updated_file = True
        else:
            print("      [DISCARDED] Field 'clean_highlighted_title' not added.")
            summary_counts["Discarded (Failed validation / Null)"] += 1

        print("      [Timer] Waiting 13 seconds before next call...")
        time.sleep(13)

    if updated_file:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"\n[OK] Changes written to {os.path.basename(json_path)}")
    else:
        print(f"\n[SKIP] No new highlights updated for {os.path.basename(json_path)}")

    print("\n" + "-" * 60)
    print("SUMMARY")
    for category, count in summary_counts.items():
        print(f"{category} : {count}")
    print("=" * 60)

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
        
    print("\n✅ All highlighting completed successfully.")

if __name__ == "__main__":
    main()
