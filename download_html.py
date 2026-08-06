import json
import os
import time
import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "data/reviews/reviews_2026-bhai-tera-star-hai.json"
OUTPUT_DIR = "data/webpages/html_2026-bhai-tera-star-hai"
MIN_VALID_HTML_BYTES = 2000  # HTML smaller than this is treated as a WAF block

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


def fallback_download(url):
    """Fallback HTTP fetcher for sites that block Playwright or time out."""
    print("  └─► [FALLBACK] Attempting direct HTTP request...")
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=20)
        if response.status_code == 200 and len(response.text) >= MIN_VALID_HTML_BYTES:
            print(f"  └─► [FALLBACK SUCCESS] Received {len(response.text)} characters.")
            return response.text
        else:
            print(f"  └─► [FALLBACK FAILED] Status: {response.status_code}, Length: {len(response.text)}")
            return None
    except Exception as e:
        print(f"  └─► [FALLBACK ERROR] {e}")
        return None


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
        context = browser.new_context(
            user_agent=HTTP_HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Referer": "https://www.google.com/"},
        )

        success_count = 0
        error_count = 0
        skipped_na_count = 0
        skipped_already_y_count = 0

        print("\n[STEP 4] Beginning batch download loop...")

        for index, pub in enumerate(publishers, start=1):
            pub_id = pub.get("publisher_id", "unknown_publisher")
            review_url = pub.get("review_url")

            print(f"\n--- [{index}/{len(publishers)}] Processing: {pub_id} ---")

            # 1. Skip if URL is NA
            if not review_url or review_url == "NA":
                print("[SKIP] No valid URL found (NA).")
                skipped_na_count += 1
                continue

            # 2. Skip if already marked successful
            is_successful = pub.get("webpage_extraction_successful")
            if str(is_successful).upper() == "Y":
                print("[SKIP] Already successfully extracted ('Y').")
                skipped_already_y_count += 1
                continue

            output_file_name = f"webpage_{pub_id}_{movie_slug}.html"
            output_file_path = os.path.join(OUTPUT_DIR, output_file_name)

            print(f"[FETCH] URL: {review_url}")

            html_content = None

            # Primary Attempt: Playwright
            try:
                page = context.new_page()
                page.route(
                    "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,css}",
                    lambda route: route.abort(),
                )

                response = page.goto(
                    review_url, wait_until="commit", timeout=25000
                )
                page.wait_for_timeout(2000)

                temp_content = page.content()
                page.close()

                if len(temp_content) >= MIN_VALID_HTML_BYTES:
                    html_content = temp_content
                else:
                    print(
                        f"[WARNING] Playwright payload too small ({len(temp_content)} chars)."
                    )

            except Exception as e:
                print(f"[WARNING] Playwright attempt failed: {e}")

            # Secondary Attempt: Fallback HTTP Downloader (if Playwright failed or was blocked)
            if not html_content:
                html_content = fallback_download(review_url)

            # Evaluate Final Output
            if html_content and len(html_content) >= MIN_VALID_HTML_BYTES:
                print(f"[SUCCESS] Saved {len(html_content)} chars to {output_file_name}")

                with open(output_file_path, "w", encoding="utf-8") as out_file:
                    out_file.write(html_content)

                pub["webpage_extraction_successful"] = "Y"
                success_count += 1
            else:
                print(f"[ERROR] Could not extract valid HTML for {pub_id}")
                pub["webpage_extraction_successful"] = "N"
                error_count += 1

            # Persist updated status back to JSON
            with open(INPUT_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            time.sleep(2)

        browser.close()

    print("\n" + "=" * 40)
    print("BATCH DOWNLOAD COMPLETE")
    print(f"Newly processed & successful: {success_count}")
    print(f"Skipped (URL is NA): {skipped_na_count}")
    print(f"Skipped (Already 'Y'): {skipped_already_y_count}")
    print(f"Failed / Blocked: {error_count}")
    print("=" * 40)


if __name__ == "__main__":
    download_all_publishers()
