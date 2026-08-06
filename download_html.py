import json
import os
import requests

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "data/reviews/reviews_2026-bhai-tera-star-hai.json"
TARGET_PUBLISHER_ID = "the-indian-express"

OUTPUT_DIR = "data/webpages/html_2026-bhai-tera-star-hai"
OUTPUT_FILE_PATH = os.path.join(
    OUTPUT_DIR, "webpage_the-indian-express_2026-bhai-tera-star-hai.html"
)

# Realistic headers to mimic a web browser and prevent requests from being blocked
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

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

    # 5. Download the HTML page
    print("\n[STEP 6] Initiating HTTP GET request to download webpage...")
    print(f"[TRACE] Using headers: {HEADERS}")
    try:
        response = requests.get(review_url, headers=HEADERS, timeout=15)
        print(f"[TRACE] HTTP Response Status Code: {response.status_code}")
        response.raise_for_status()  # Raises an exception for 4xx and 5xx status codes
        html_content = response.text
        print(f"[TRACE] Successfully downloaded HTML payload ({len(html_content)} characters).")
    except requests.exceptions.Timeout:
        print("[ERROR] HTTP Request timed out after 15 seconds.")
        return
    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP Error occurred: {e}")
        return
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] A network or request error occurred: {e}")
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
