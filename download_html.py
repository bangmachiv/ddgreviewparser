import json
import os
from playwright.sync_api import sync_playwright

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "data/reviews/reviews_2026-bhai-tera-star-hai.json"
TARGET_PUBLISHER_ID = "the-indian-express"

OUTPUT_DIR = "data/webpages/html_2026-bhai-tera-star-hai"
OUTPUT_FILE_PATH = os.path.join(
    OUTPUT_DIR, "webpage_the-indian-express_2026-bhai-tera-star-hai.html"
)

def download_html_for_publisher():
    print("[STEP 1] Initializing script.")
    print(f"[TRACE] Target JSON path: {INPUT_JSON_PATH}")
    print(f"[TRACE] Target Publisher ID: {TARGET_PUBLISHER_ID}")

    # 1. Verify input JSON file exists
    print("\n[STEP 2] Verifying JSON file exists...")
    if not os.path.exists(INPUT_JSON_PATH):
        print(f"[ERROR] Input JSON file not found at: {INPUT_JSON_PATH}")
        return
    print("[TRACE] JSON file located successfully.")

    # 2. Read and parse JSON data
    print("\n[STEP 3] Reading JSON data...")
    try:
        with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        print("[TRACE] JSON data loaded into memory successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to parse JSON file: {e}")
        return

    # 3. Locate target publisher
    print("\n[STEP 4] Searching for target publisher in JSON...")
    publishers = data.get("publishers", [])
    print(f"[TRACE] Found {len(publishers)} total publishers in JSON.")
    
    target_publisher = next(
        (p for p in publishers if p.get("publisher_id") == TARGET_PUBLISHER_ID),
        None,
    )

    if not target_publisher:
        print(f"[ERROR] Publisher ID '{TARGET_PUBLISHER_ID}' was not found in the JSON array.")
        return
    print(f"[TRACE] Match found for publisher: {target_publisher.get('publisher_name')}")

    # 4. Extract and validate URL
    print("\n[STEP 5] Validating review URL...")
    review_url = target_publisher.get("review_url")
    if not review_url or review_url == "NA":
        print(f"[ERROR] Invalid or missing review URL. Value is: '{review_url}'")
        return
    print(f"[TRACE] Valid URL extracted: {review_url}")

    # 5. Download the HTML page using Playwright
    print("\n[STEP 6] Initiating headless browser request using Playwright...")
    try:
        with sync_playwright() as p:
            print("[TRACE] Launching Chromium browser...")
            browser = p.chromium.launch(headless=True)
            
            # Use a realistic User-Agent and viewport to mimic a real desktop user
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )
            
            page = context.new_page()
            print(f"[TRACE] Navigating to: {review_url}")
            
            # Wait until the DOM is loaded to ensure we get the content
            response = page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
            
            if response:
                print(f"[TRACE] HTTP Response Status Code: {response.status}")
                if response.status >= 400:
                    print(f"[ERROR] Playwright received an HTTP error status: {response.status}")
                    # We continue anyway, as Cloudflare challenge pages sometimes return 403s 
                    # but still load HTML that we want to inspect for RCA.
            
            html_content = page.content()
            print(f"[TRACE] Successfully downloaded HTML payload ({len(html_content)} characters).")
            
            browser.close()
            print("[TRACE] Browser closed successfully.")
            
    except Exception as e:
        print(f"[ERROR] Playwright encountered a network or execution error: {e}")
        return

    # 6. Ensure output directory exists
    print("\n[STEP 7] Checking output directory...")
    print(f"[TRACE] Target output directory: {OUTPUT_DIR}")
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        print("[TRACE] Output directory is ready (created if not existed).")
    except Exception as e:
        print(f"[ERROR] Failed to create output directory: {e}")
        return

    # 7. Write HTML to target file
    print("\n[STEP 8] Writing HTML data to local file...")
    print(f"[TRACE] Target file path: {OUTPUT_FILE_PATH}")
    try:
        with open(OUTPUT_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(html_content)
        print("[TRACE] File write operation completed successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to write HTML to file: {e}")
        return

    print("\n[SUCCESS] Script executed perfectly. Webpage HTML is saved and ready for extraction.")

if __name__ == "__main__":
    download_html_for_publisher()
