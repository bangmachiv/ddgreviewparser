import json
import os
import time
from google import genai
from google.genai import errors

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "classify_unrated.txt")
LIVE_MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")

VALID_CATEGORIES = ["GOOD", "NEUTRAL", "BAD"]

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
# Helper Functions
# ---------------------------------------------------------------------------
def is_missing_star_rating(val):
    """Determines if the star rating is genuinely missing or invalid."""
    if val in (None, "", "Na", "NA", "null") or "could not find" in str(val).lower():
        return True
    try:
        float(val)
        return False # It's a valid number, so it's NOT missing
    except ValueError:
        return True

def clean_ai_response(text):
    """Strips markdown and whitespace to get the raw word."""
    text = text.strip().upper()
    text = text.replace("`", "").replace("*", "").replace('"', '').replace("'", "")
    return text

def fetch_category_with_fallback(movie_name, clean_title, prompt_template):
    """Calls Gemini with fallback models and strict validation."""
    prompt = prompt_template.replace("{movie_name}", movie_name).replace("{clean_title}", clean_title)
    
    active_models = sorted(
        [m for m in MODEL_CONFIG if m.get("enabled", True)],
        key=lambda x: x.get("priority", 999)
    )

    for model_info in active_models:
        model_name = model_info["name"]
        print(f"      [Attempting Model: {model_name}]")
        
        try:
            # Not using JSON mime type here because we just want one plain text word
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            
            if response and response.text:
                raw_text = response.text.strip()
                print(f"      [DEBUG Raw Gemini Response]: {raw_text}")
                
                category = clean_ai_response(raw_text)
                
                # Strict Validation
                if category in VALID_CATEGORIES:
                    return category
                else:
                    print(f"      [Validation Failed] '{category}' is not GOOD, NEUTRAL, or BAD.")
                    print("      [Attempting fallback...]")
        except errors.APIError as e:
            print(f"      [API Error on {model_name}]: {e.message}")
        except Exception as e:
            print(f"      [Unexpected Error on {model_name}]: {e}")
            
        print("      [Waiting 3s before fallback model attempt...]")
        time.sleep(3)
        
    return None

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

def process_movie_file(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" CLASSIFYING UNRATED TITLES FOR: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Extract the movie name for context
    movie_name = data.get("movie", {}).get("name", "Unknown Movie")
    publishers = data.get("publishers", [])
    
    updated_file = False
    summary_counts = {
        "Skipped (Has Star Rating)": 0,
        "Skipped (No clean_title)": 0,
        "Skipped (Already Classified)": 0,
        "Successfully Classified": 0,
        "Failed Classification": 0
    }

    for pub in publishers:
        pub_id = pub.get("publisher_id", "Unknown")
        clean_title = pub.get("clean_title")
        star_rating = pub.get("star_rating")
        ai_category = pub.get("ai_assigned_category")

        # Skip if no clean_title is present
        if not clean_title or not str(clean_title).strip():
            summary_counts["Skipped (No clean_title)"] += 1
            continue
            
        # Skip if it already has a valid star rating
        if not is_missing_star_rating(star_rating):
            summary_counts["Skipped (Has Star Rating)"] += 1
            continue
            
        # Skip if already successfully classified
        if ai_category in VALID_CATEGORIES:
            summary_counts["Skipped (Already Classified)"] += 1
            continue

        print(f"\n  [*] Processing [{pub_id}]")
        print(f"      Title: {clean_title}")

        # Pass the movie_name into the fallback function
        category = fetch_category_with_fallback(movie_name, clean_title, prompt_template)
        
        if category:
            pub["ai_assigned_category"] = category
            print(f"      [SUCCESS] Assigned Category: {category}")
            summary_counts["Successfully Classified"] += 1
            updated_file = True
        else:
            print("      [DISCARDED] Failed to extract a valid category.")
            summary_counts["Failed Classification"] += 1

        # Respect API Rate limits
        print("      [Timer] Waiting 13 seconds before next call...")
        time.sleep(13)

    # Save updates back to JSON
    if updated_file:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print(f"\n[OK] Changes written to {os.path.basename(json_path)}")
    else:
        print(f"\n[SKIP] No new classifications were made for {os.path.basename(json_path)}")

    print("\n" + "-" * 60)
    print("SUMMARY")
    for category_name, count in summary_counts.items():
        print(f"{category_name} : {count}")
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
        
    print("\n✅ All AI classifications completed successfully.")

if __name__ == "__main__":
    main()
