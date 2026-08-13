import json
import os
import glob
import time
import re
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
def clean_html(html_content):
    """
    Strips out massive base64 image strings to save tokens, 
    but preserves the raw HTML/DOM completely intact.
    """
    return re.sub(r'data:image\/[^;]+;base64,[^"\'\s]+', '', html_content)

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
    prompt = prompt_template.replace("{movie_name}", str(movie_name)).replace("{webpage_text}", str(html_text))
    
    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
        
        if response and response.text:
            raw_json = response.text.strip()
            if raw_json.startswith("```json"):
                raw_json = raw_json[7:]
            elif raw_json.startswith("```"):
                raw_json = raw_json[3:]
            if raw_json.endswith("```"):
                raw_json = raw_json[:-3]
                
            raw_json = raw_json.strip()
            
            if not raw_json.startswith("{"):
                raw_json = "{" + raw_json
                
            return json.loads(raw_json)
            
    except errors.APIError as e:
        print(f"      [API Error]: Status Code {e.code} - {e.message}")
    except json.JSONDecodeError as e:
        print(f"      [JSON Parse Error]: {e} \n      [Raw Output]: {raw_json[:100]}...")
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
    bad_values = ["na", "could not find from jsonld", "none", "null", ""]

    for pub in publishers:
        if needs_extraction(pub):
            pub_id = pub.get("publisher_id", "unknown")
            current_attempts = pub.get("ai_extraction_attempt_count", 0)
            
            print(f"\n  [*] Processing [{pub_id}] - Attempt {current_attempts + 1}/5")
            pub["ai_extraction_attempt_count"] = current_attempts + 1
            
            html_path = os.path.join(html_dir, f"webpage_{pub_id}_{movie_slug}.html")
            if not os.path.exists(html_path):
                print(f"      [SKIP] HTML file not found at {html_path}")
                continue
                
            with open(html_path, "r", encoding="utf-8") as hf:
                raw_html = hf.read()
                
            cleaned_html = clean_html(raw_html)
            
            # Slice into 800,000 character chunks to stay safely under the 250k TPM limit
            chunk_size = 800000
            chunks = [cleaned_html[i:i+chunk_size] for i in range(0, len(cleaned_html), chunk_size)]
            print(f"      [HTML size: {len(cleaned_html)} chars -> Split into {len(chunks)} chunk(s)]")

            # Load currently known data so we don't overwrite good data
            current_critic = str(pub.get("critic_name", "NA"))
            current_rating = str(pub.get("star_rating", "NA"))
            found_new_data = False

            for idx, chunk in enumerate(chunks):
                missing_critic = current_critic.strip().lower() in bad_values
                missing_rating = current_rating.strip().lower() in bad_values

                print(f"      [Calling Gemini 3.5 Flash Lite... Chunk {idx + 1}/{len(chunks)}]")
                
                extracted_data = extract_metadata_with_gemini(movie_name, chunk, prompt_template)
                
                if extracted_data:
                    new_critic = str(extracted_data.get("critic_name", "NA"))
                    new_rating = str(extracted_data.get("star_rating", "NA"))
                    
                    if missing_critic and new_critic.strip().lower() not in bad_values:
                        current_critic = new_critic
                        pub["critic_name"] = current_critic
                        print(f"      => Extracted Critic: {current_critic}")
                        found_new_data = True
                        
                    if missing_rating and new_rating.strip().lower() not in bad_values:
                        current_rating = new_rating
                        pub["star_rating"] = current_rating
                        print(f"      => Extracted Rating: {current_rating}")
                        found_new_data = True

                # Apply strict 65-second sleep to respect the 1 RPM rolling window and prevent 429 errors
                print("      [Waiting 65 seconds to respect 1 RPM limit...]")
                time.sleep(65)

                # Check if we now have both fields. If yes, stop processing chunks.
                missing_critic = current_critic.strip().lower() in bad_values
                missing_rating = current_rating.strip().lower() in bad_values
                
                if not missing_critic and not missing_rating:
                    print("      [Found both fields. Halting chunk processing for this publisher.]")
                    break

            # Update final AI Extraction Status for this publisher
            if not missing_critic and not missing_rating:
                pub["ai_extraction_status"] = "found both"
            elif not missing_critic or not missing_rating:
                pub["ai_extraction_status"] = "found one"
            else:
                pub["ai_extraction_status"] = "found none"
                
            print(f"      [Final Status]: {pub['ai_extraction_status'].upper()}")

            if found_new_data:
                current_ld_status = pub.get("json_ld_extraction_status", "")
                if "Augmented by Gemini" not in current_ld_status:
                    pub["json_ld_extraction_status"] = f"{current_ld_status} | Augmented by Gemini"
                updated_count += 1

            # Save progress iteratively so we don't lose data if the script crashes later
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

    if updated_count > 0:
        print(f"\n  -> Finished processing. Saved updates for {updated_count} publisher(s).")
    else:
        print("\n  -> Finished processing. Attempt counters updated. No new metadata extracted.")

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
