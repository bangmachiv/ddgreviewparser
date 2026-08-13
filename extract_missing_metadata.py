import json
import os
import glob
import time
import re
from bs4 import BeautifulSoup
from google import genai
from google.genai import errors

# ---------------------------------------------------------------------------
# Setup & Absolute Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(BASE_DIR, "prompt_missing_metadata.txt")

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("[ERROR] GEMINI_API_KEY environment variable not found!")
    exit(1)

client = genai.Client(api_key=API_KEY)

# Using Flash Lite exclusively to utilize the 500 RPD limit
MODEL_NAME = "gemini-3.5-flash-lite" 

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean_html_to_text(html_content):
    """Strips tags, scripts, and styles to return pure readable text."""
    soup = BeautifulSoup(html_content, "lxml")
    for script_or_style in soup(["script", "style", "noscript", "meta", "head"]):
        script_or_style.decompose()
    text = soup.get_text(separator=' ', strip=True)
    # Truncate to roughly 50,000 characters to stay well within token limits
    return text[:50000] 

def needs_extraction(pub):
    """Determines if a publisher needs Gemini fallback extraction and is eligible."""
    url = pub.get("review_url", "")
    if not url or url.strip().upper() == "NA":
        return False
        
    # Circuit Breaker: Do not attempt if we've already tried 5 or more times
    attempts = pub.get("ai_extraction_attempt_count", 0)
    if attempts >= 5:
        return False
        
    bad_values = ["na", "could not find from jsonld", "none", "null", ""]
    critic = str(pub.get("critic_name", "")).strip().lower()
    rating = str(pub.get("star_rating", "")).strip().lower()
    
    # If both fields are already populated and valid, skip
    if critic not in bad_values and rating not in bad_values:
        return False
        
    return True

def extract_metadata_with_gemini(movie_name, html_text, prompt_template):
    prompt = prompt_template.format(movie_name=movie_name, webpage_text=html_text)
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
        
        if response and response.text:
            # Clean markdown code blocks if the LLM includes them
            raw_json = response.text.strip()
            if raw_json.startswith("```json"):
                raw_json = raw_json[7:]
            if raw_json.startswith("```"):
                raw_json = raw_json[3:]
            if raw_json.endswith("```"):
                raw_json = raw_json[:-3]
                
            return json.loads(raw_json.strip())
            
    except errors.APIError as e:
        print(f"      [API Error]: Status Code {e.code} - {e.message}")
    except json.JSONDecodeError:
        print(f"      [JSON Parse Error]: The model did not return valid JSON.")
    except Exception as e:
        print(f"      [Unexpected Error]: {e}")
        
    return None

# ---------------------------------------------------------------------------
# Main Logic
# ---------------------------------------------------------------------------
def process_movie_file(json_path, prompt_template):
    print("\n" + "="*80)
    print(f" CHECKING MISSING METADATA: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_name = data.get("movie", {}).get("name")
    movie_slug = data.get("movie", {}).get("slug")
    publishers = data.get("publishers", [])

    html_dir = os.path.join(BASE_DIR, "data", "webpages", f"html_{movie_slug}")
    updated_count = 0

    for pub in publishers:
        if needs_extraction(pub):
            pub_id = pub.get("publisher_id", "unknown")
            current_attempts = pub.get("ai_extraction_attempt_count", 0)
            
            print(f"\n  [*] Processing [{pub_id}] - Attempt {current_attempts + 1}/5")
            
            # Increment attempt counter immediately
            pub["ai_extraction_attempt_count"] = current_attempts + 1
            
            html_path = os.path.join(html_dir, f"webpage_{pub_id}_{movie_slug}.html")
            if not os.path.exists(html_path):
                print(f"      [SKIP] HTML file not found at {html_path}")
                continue
                
            with open(html_path, "r", encoding="utf-8") as hf:
                raw_html = hf.read()
                
            clean_text = clean_html_to_text(raw_html)
            print("      [Calling Gemini 3.5 Flash Lite...]")
            
            extracted_data = extract_metadata_with_gemini(movie_name, clean_text, prompt_template)
            
            if extracted_data:
                critic = extracted_data.get("critic_name", "NA")
                rating = extracted_data.get("star_rating", "NA")
                
                bad_values = ["na", "could not find from jsonld", "none", "null", ""]
                
                ai_found_critic = str(critic).strip().lower() not in bad_values
                ai_found_rating = str(rating).strip().lower() not in bad_values
                
                # Determine and log the AI Extraction Status
                if ai_found_critic and ai_found_rating:
                    pub["ai_extraction_status"] = "found both"
                elif ai_found_critic or ai_found_rating:
                    pub["ai_extraction_status"] = "found one"
                else:
                    pub["ai_extraction_status"] = "found none"
                    
                print(f"      [Status]: {pub['ai_extraction_status'].upper()}")

                # Only overwrite if Gemini actually found something valid
                if ai_found_critic:
                    print(f"      => Extracted Critic: {critic}")
                    pub["critic_name"] = critic
                    
                if ai_found_rating:
                    print(f"      => Extracted Rating: {rating}")
                    pub["star_rating"] = str(rating)
                
                # Append legacy status for tracking
                current_ld_status = pub.get("json_ld_extraction_status", "")
                if "Augmented by Gemini" not in current_ld_status:
                    pub["json_ld_extraction_status"] = f"{current_ld_status} | Augmented by Gemini"
                    
                updated_count += 1
            else:
                pub["ai_extraction_status"] = "failed to parse"
                print("      [Failed] Could not extract data via Gemini.")

            # 15 RPM limit = 4 seconds per request. 4.5 gives us a safety buffer.
            print("      [Waiting 4.5 seconds for rate limit...]")
            time.sleep(4.5) 

    # Always save if we incremented counters, even if data wasn't found
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        
    if updated_count > 0:
        print(f"\n  -> Saved updates for {updated_count} publisher(s).")
    else:
        print("\n  -> Attempt counters updated. No new metadata extracted for this movie.")

def main():
    if not os.path.exists(PROMPT_FILE):
        print(f"[FATAL] Prompt file '{PROMPT_FILE}' not found!")
        return
        
    with open(PROMPT_FILE, "r", encoding="utf-8") as pf:
        prompt_template = pf.read()

    target_files = glob.glob(os.path.join(BASE_DIR, "data", "reviews", "reviews_*.json"))
    
    if not target_files:
        print("[ERROR] No JSON files found.")
        return

    for json_path in target_files:
        process_movie_file(json_path, prompt_template)

if __name__ == "__main__":
    main()
