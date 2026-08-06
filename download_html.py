import json
import os
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "data/reviews/reviews_2026-bhai-tera-star-hai.json"
OUTPUT_DIR = "data/webpages/html_2026-bhai-tera-star-hai"
MIN_VALID_HTML_BYTES = 2000  # Payloads smaller than this are WAF block pages

def download_all_publishers():
    print("[STEP 1] Initializing batch download script.")

    if not os.path.exists(INPUT_JSON_PATH):
        print(f"[ERROR] Input JSON file not found at: {INPUT_JSON_PATH}")
        return

    print("[STEP 2] Loading JSON data...")
    with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_slug = data.get("movie", {}).get("slug", "unknown_movie")
    publishers = data.get("publishers", [])
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("\n[STEP 3] Launching headless browser with Stealth v2.0...")
    
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        
        # Inject realistic headers to help bypass 403 blocks (Indian Express / Moneycontrol)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/"
            }
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

            # 2. Skip if already successfully extracted in JSON (Handles missing field automatically)
            is_successful = pub.get("webpage_extraction_successful")
            if str(is_successful).upper() == "Y":
                print(f"[SKIP] JSON already marked 'webpage_extraction_successful': 'Y'")
                skipped_count += 1
                continue

            output_file_name = f"webpage_{pub_id}_{movie_slug}.html"
            output_file_path = os.path.join(OUTPUT_DIR, output_file_name)

            print(f"[FETCH] URL: {review_url}")
            
            try:
                page = context.new_page()
                
                # OPTIMIZATION: Block heavy assets (Fixes the Rediff timeout issue)
                page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,css}", lambda route: route.abort())
                
                # Wait until 'commit' instead of 'domcontentloaded' to grab HTML immediately 
                response = page.goto(review_url, wait_until="commit", timeout=45000)
                
                # Give the DOM 3 seconds to populate standard text before we snapshot it
                page.wait_for_timeout(3000)
                
                html_content = page.content()
                
                if len(html_content) < MIN_VALID_HTML_BYTES:
                    print(f"[WARNING] Content too small ({len(html_content)} chars). Likely a 403 block.")
                    pub["webpage_extraction_successful"] = "N"
                    error_count += 1
                else:
                    print(f"[SUCCESS] Saved {len(html_content)} chars to {output_file_name}")
                    
                    # 1. Save HTML file
                    with open(output_file_path, "w", encoding="utf-8") as out_file:
                        out_file.write(html_content)
                    
                    # 2. Update JSON node with Success Flag
                    pub["webpage_extraction_successful"] = "Y"
                    success_count += 1
                    
                # 3. Save JSON state dynamically inside the loop! 
                # (This ensures if script crashes on publisher 20, the first 19 are safely marked "Y")
                with open(INPUT_JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                
                page.close()
                time.sleep(2)
                
            except Exception as e:
                print(f"[ERROR] Failed to download {pub_id}: {e}")
                pub["webpage_extraction_successful"] = "N"
                error_count += 1
                
                # Save the "N" failure state to JSON
                with open(INPUT_JSON_PATH, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)

        print("\n[STEP 5] Cleaning up browser...")
        browser.close()

    print("\n" + "="*40)
    print("BATCH DOWNLOAD COMPLETE")
    print(f"Successfully newly downloaded: {success_count}")
    print(f"Skipped (NA / Already 'Y'): {skipped_count}")
    print(f"Errors/Blocked: {error_count}")
    print("="*40)

if __name__ == "__main__":
    download_all_publishers()
