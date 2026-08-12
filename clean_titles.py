import json
import os
import glob
import re
import time
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Gemini API & File Setup
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("[ERROR] GEMINI_API_KEY environment variable not found!")
    exit(1)

genai.configure(api_key=API_KEY)

PROMPT_FILE = "prompt_clean_titles.txt"

# Priority-ordered model configuration
MODEL_CONFIG = [
    {
        "name": "models/gemini-3.6-flash",
        "priority": 1,
        "enabled": True
    },
    {
        "name": "models/gemini-3.5-flash",
        "priority": 2,
        "enabled": True
    },
    {
        "name": "models/gemini-3.5-flash-lite",
        "priority": 3,
        "enabled": True
    },
    {
        "name": "models/gemini-3.1-flash-lite",
        "priority": 4,
        "enabled": True
    }
]


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------
def extract_words(text):
    """Extracts lowercased unicode word tokens from text, ignoring punctuation."""
    if not text:
        return []
    return re.findall(r'\w+', text.lower(), re.UNICODE)


def validate_cleaned_title(cleaned_title, original_title):
    """
    Validates that:
    1. Cleaned title is non-empty.
    2. EVERY word in cleaned_title exists in original_title.
    """
    if not cleaned_title or not cleaned_title.strip():
        return False

    clean_words = extract_words(cleaned_title)
    if not clean_words:
        return False

    original_words_set = set(extract_words(original_title))

    # Strict check: Every word in the output MUST exist in the original title
    for word in clean_words:
        if word not in original_words_set:
            print(f"      [Validation Fail] Word '{word}' is not in the original title!")
            return False

    return True


# ---------------------------------------------------------------------------
# Core Gemini Cleaning Logic
# ---------------------------------------------------------------------------
def clean_title_with_gemini(movie_name, raw_title, models_config, prompt_template):
    """Iterates through enabled models by priority to extract cleaned title."""
    active_models = sorted(
        [m for m in models_config if m.get("enabled", True)],
        key=lambda x: x.get("priority", 999)
    )

    # Inject the variables into the template loaded from the text file
    prompt = prompt_template.format(movie_name=movie_name, raw_title=raw_title)

    for model_info in active_models:
        model_name = model_info["name"]
        print(f"      [Attempting Model: {model_name}]")

        try:
            # Instantiate model without tools or web search parameters
            model = genai.GenerativeModel(model_name)
            
            # Explicit call with NO tools parameter specified
            response = model.generate_content(prompt)

            if response and response.text:
                cleaned = response.text.strip()
                
                # Strip wrapping quotes if added by model
                if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
                    cleaned = cleaned[1:-1].strip()

                # CHECK: Non-null and strict word containment check
                if validate_cleaned_title(cleaned, raw_title):
                    print(f"      [Success with {model_name}]")
                    return cleaned
                else:
                    print(f"      [Output Rejected] Output failed strict word containment check.")

        except Exception as e:
            print(f"      [API Error on {model_name}]: {e}")

        # 5-SECOND GAP: Pause before attempting a fallback model
        print("      [Waiting 5 seconds before model fallback attempt...]")
        time.sleep(5)  

    return None


# ---------------------------------------------------------------------------
# File Processing & Pipeline Integration
# ---------------------------------------------------------------------------
def get_live_movie_slugs():
    slugs = []
    live_master_file = "data/movies/movies-live-today.json"
    if os.path.exists(live_master_file):
        with open(live_master_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            movie_list = data if isinstance(data, list) else data.get("movies", [])
            for movie in movie_list:
                if isinstance(movie, dict) and "slug" in movie:
                    slugs.append(movie["slug"])
    else:
        for file_path in glob.glob("data/movies/*.json"):
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    slug = data.get("slug") or data.get("movie", {}).get("slug")
                    if slug:
                        slugs.append(slug)
                except Exception:
                    pass
    return list(set(slugs))


def process_cleaning_for_movie(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" CLEANING TITLES FOR LIVE MOVIE FILE: {json_path}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_name = data.get("movie", {}).get("name")
    movie_slug = data.get("movie", {}).get("slug")
    publishers = data.get("publishers", [])

    summary_counts = {
        "Skipped (No article_title)": 0,
        "Skipped (Already cleaned)": 0,
        "Cleaned successfully": 0,
        "Discarded (Failed validation / Null)": 0
    }

    for pub in publishers:
        pub_id = pub.get("publisher_id")
        raw_title = pub.get("article_title")
        existing_clean_title = pub.get("clean_title")

        if not raw_title:
            summary_counts["Skipped (No article_title)"] += 1
            continue

        if existing_clean_title:
            summary_counts["Skipped (Already cleaned)"] += 1
            continue

        print(f"\n  [*] Processing [{pub_id}]...")
        print(f"      Raw Title: {raw_title}")

        cleaned = clean_title_with_gemini(movie_name, raw_title, MODEL_CONFIG, prompt_template)

        if cleaned:
            pub["clean_title"] = cleaned
            print(f"      Saved clean_title: {cleaned}")
            summary_counts["Cleaned successfully"] += 1
        else:
            # DISCARD STEP: Ensure clean_title field is completely omitted/removed
            if "clean_title" in pub:
                del pub["clean_title"]
            print(f"      [DISCARDED] Output invalid or null. 'clean_title' field omitted.")
            summary_counts["Discarded (Failed validation / Null)"] += 1

        # 13-SECOND GAP: Ensures max ~4.6 RPM to strictly respect the 5 RPM free-tier limit
        print("      [Waiting 13 seconds before next API call...]")
        time.sleep(13)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print("\n" + "-" * 60)
    print(f"SUMMARY FOR: {movie_slug}")
    for category, count in summary_counts.items():
        print(f"{category} : {count}")
    print("=" * 60)


def main():
    print("[STEP 1] Loading prompt template...")
    if not os.path.exists(PROMPT_FILE):
        print(f"[ERROR] Prompt file '{PROMPT_FILE}' not found! Please create it.")
        return
        
    with open(PROMPT_FILE, "r", encoding="utf-8") as pf:
        prompt_template = pf.read()

    print("[STEP 2] Fetching live movies for title cleaning...")
    live_slugs = get_live_movie_slugs()

    if not live_slugs:
        print("[ERROR] No live movies found. Exiting.")
        return

    target_files = []
    for slug in live_slugs:
        review_file = f"data/reviews/reviews_{slug}.json"
        if os.path.exists(review_file):
            target_files.append(review_file)

    print("\n[STEP 3] Running Gemini cleaning pipeline...")
    for json_path in target_files:
        process_cleaning_for_movie(json_path, prompt_template)


if __name__ == "__main__":
    main()
