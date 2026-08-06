import json
import os
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync  # The magic anti-403 shield

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "data/reviews/reviews_2026-bhai-tera-star-hai.json"
OUTPUT_DIR = "data/webpages/html_2026-bhai-tera-star-hai"

def download_all_publishers():
    print("[STEP 1] Initializing batch download script.")

    if not os.path.exists(INPUT_JSON_PATH):
        print(f"[ERROR] Input JSON file not found at: {INPUT_JSON_PATH}")
        return

    print("[STEP 2] Loading JSON data...")
    try:
        with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to parse JSON file: {e}")
        return

    movie_slug = data.get("movie", {}).get("slug", "unknown_movie")
    publishers = data.get("publishers", [])
    print(f"[TRACE] Loaded {len(publishers)} publishers for movie: {movie_slug}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\n[STEP 3] Launching headless browser with Stealth...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        
        success_count = 0
        error_count = 0
        skipped_count = 0

        print("\n[STEP 4] Beginning batch download loop...")
        
        for index, pub in enumerate(publishers, start=1):
            pub_id = pub.get("publisher_id", "unknown_publisher")
            review_url = pub.get("review_url")
            
            print(f"\n--- [{index}/{len(publishers)}] Processing: {pub_id} ---")

            # 1. Skip if URL is NA
            if not review_url or review_url == "NA":
                print(f"[SKIP] No valid URL found.")
                skipped_count += 1
                continue

            output_file_name = f"webpage_{pub_id}_{movie_slug}.html"
            output_file_path = os.path.join(OUTPUT_DIR, output_file_name)

            # 2. Skip if already downloaded (prevents re-downloading if script restarts)
            if os.path.exists(output_file_path):
                print(f"[SKIP] File already exists: {output_file_name}")
                skipped_count += 1
                continue

            print(f"[FETCH] URL: {review_url}")
            
            try:
                # Create a fresh page for each URL and apply Stealth!
                page = context.new_page()
                stealth_sync(page)
                
                response = page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
                
                if response and response.status >= 400:
                    print(f"[WARNING] HTTP Status {response.status}")
                
                html_content = page.content()
                
                with open(output_file_path, "w", encoding="utf-8") as out_file:
                    out_file.write(html_content)
                
                print(f"[SUCCESS] Saved {len(html_content)} chars to {output_file_name}")
                success_count += 1
                
                # Close the page to free up memory before the next loop
                page.close()
                
                # Sleep to avoid rate-limiting
                time.sleep(2)
                
            except Exception as e:
                print(f"[ERROR] Failed to download {pub_id}: {e}")
                error_count += 1

        print("\n[STEP 5] Cleaning up browser...")
        browser.close()

    print("\n" + "="*40)
    print("BATCH DOWNLOAD COMPLETE")
    print(f"Successfully downloaded: {success_count}")
    print(f"Skipped (NA/Exists): {skipped_count}")
    print(f"Errors: {error_count}")
    print("="*40)

if __name__ == "__main__":
    download_all_publishers()
