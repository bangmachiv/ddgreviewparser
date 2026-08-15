import json
import os
import re
import time
from google import genai
from google.genai import errors

# ---------------------------------------------------------------------------
# Path Configuration (Assuming script runs from ddgreviewparser root)
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "find_title_highlight.txt")
LIVE_MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")

# ---------------------------------------------------------------------------
# Gemini API Setup
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("[ERROR] GEMINI_API_KEY environment variable not found!")
    exit(1)

client = genai.Client(api_key=API_KEY)
MODEL_NAME = "gemini-3.5-flash-lite"

# ---------------------------------------------------------------------------
# Validation & Formatting Logic
# ---------------------------------------------------------------------------
def clean_json_response(text):
    """Strips Markdown code blocks if Gemini returns them."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def process_and_validate_highlight(clean_title, gemini_response_text):
    """
    Validates Gemini's JSON response against all strict rules.
    If it passes, returns the new string with the first occurrence of keywords wrapped in asterisks.
    If it fails ANY rule, returns None.
    """
    if not gemini_response_text or not gemini_response_text.strip():
        print("      [FAIL] Gemini returned empty response.")
        return None

    try:
        raw_json = clean_json_response(gemini_response_text)
        keywords = json.loads(raw_json)
    except json.JSONDecodeError:
        print("      [FAIL] Gemini response is not valid JSON.")
        return None

    # Rule: Must be a list
    if not isinstance(keywords, list):
        print("      [FAIL] Gemini response is not a JSON array.")
        return None

    # Rule: 0 words in response OR more than 3 items
    if len(keywords) == 0:
        print("      [FAIL] 0 keywords returned.")
        return None
    if len(keywords) > 3:
        print(f"      [FAIL] Too many keywords returned ({len(keywords)}). Max is 3.")
        return None

    clean_title_lower = clean_title.lower()
    valid_keywords = []

    for kw in keywords:
        kw = str(kw).strip()
        if not kw:
            continue
        
        # Rule: Any 1 phrase cannot have more than 3 words
        if len(kw.split()) > 3:
            print(f"      [FAIL] Phrase '{kw}' has more than 3 words.")
            return None
            
        # Rule: Must be part of the cleaned title
        if kw.lower() not in clean_title_lower:
            print(f"      [FAIL] Phrase '{kw}' is NOT found in the original title.")
            return None
            
        valid_keywords.append(kw)

    # Sort keywords by length descending (e.g. process "slapstick comedy" BEFORE "comedy")
    # This prevents asterisks from breaking the regex search of longer overlapping phrases.
    valid_keywords.sort(key=len, reverse=True)

    # Generate the highlighted title
    highlighted_title = clean_title
    for kw in valid_keywords:
        # regex \b ensures whole-word boundaries, count=1 limits to first occurrence, (?i) is case-insensitive
        highlighted_title = re.sub(
            rf'(?i)\b({re.escape(kw)})\b', 
            r'*\1*', 
            highlighted_title, 
            count=1
        )

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

def fetch_highlights_from_gemini(movie_name, clean_title, prompt_template):
    prompt = prompt_template.replace("{movie_name}", movie_name).replace("{clean_title}", clean_title)
    
    attempts = 3
    for attempt in range(attempts):
        print(f"      [API Call] {MODEL_NAME} (Attempt {attempt+1}/{attempts})")
        try:
            # Enforce JSON output type directly at the API level
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config={"response_mime_type": "application/json"}
            )
            return response.text
            
        except errors.APIError as e:
            print(f"      [API Error]: {e.message}")
        except Exception as e:
            print(f"      [Error]: {str(e)}")
            
        if attempt < attempts - 1:
            print("      [Waiting 5s for retry...]")
            time.sleep(5)
            
    return None

def process_movie_file(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" HIGHLIGHTING TITLES FOR: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_name = data.get("movie", {}).get("name", "Unknown Movie")
    publishers = data.get("publishers", [])
    
    processed_count = 0
    updated_file = False

    for pub in publishers:
        pub_id = pub.get("publisher_id", "Unknown")
        clean_title = pub.get("clean_title")
        existing_highlight = pub.get("clean_highlighted_title")

        # Skip if no clean_title is present
        if not clean_title or not str(clean_title).strip():
            continue
            
        # Skip if it already has a highlighted title
        if existing_highlight and str(existing_highlight).strip():
            continue

        print(f"\n  [*] Processing [{pub_id}]")
        print(f"      Title: {clean_title}")

        # Call Gemini
        raw_response = fetch_highlights_from_gemini(movie_name, clean_title, prompt_template)
        
        if raw_response:
            # Validate and Apply
            highlighted = process_and_validate_highlight(clean_title, raw_response)
            
            if highlighted:
                pub["clean_highlighted_title"] = highlighted
                print(f"      [SUCCESS] Saved: {highlighted}")
                updated_file = True
            else:
                print("      [DISCARDED] Output failed validation. Field not added.")
        else:
            print("      [DISCARDED] Gemini returned no response.")

        # Respect API Rate limits
        print("      [Timer] Waiting 13 seconds before next call...")
        time.sleep(13)
        processed_count += 1

    # Save updates back to JSON
    if updated_file:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"\n[OK] Saved {os.path.basename(json_path)}")
    else:
        print(f"\n[SKIP] No new highlights were added for {os.path.basename(json_path)}")

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
