import json
import os
import time
import glob
import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
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
    print("    └─► [FALLBACK] Attempting direct HTTP request...")
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=20)
        if response.status_code == 200 and len(response.text) >= MIN_VALID_HTML_BYTES:
            print(f"    └─► [FALLBACK SUCCESS] Received {len(response.text)} characters.")
            return response.text
        else:
            print(f"    └─► [FALLBACK FAILED] Status: {response.status_code}, Length: {len(response.text)}")
            return None
    except Exception as e:
        print(f"    └─► [FALLBACK ERROR] {e}")
        return None

def process_single_movie(json_path, context):
    """Processes a single movie's review JSON file dynamically."""
    print(f"\n" + "="*60)
    print(f" LOADING TARGET: {json_path}")
    print("="*60)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Dynamically figure out the movie slug and paths
    movie_slug = data.get("movie", {}).get("slug")
    
    if not movie_slug:
        print(f"[ERROR] Could not find 'slug' inside {json_path}. Skipping.")
        return

    output_dir = f"data/webpages/html_{movie_slug}"
    os.makedirs(output_dir, exist_ok=True)  # Create the folder if it doesn't exist
    publishers = data.get("publishers", [])

    print(f" -> Movie Slug: {movie_slug}")
    print(f" -> Output Folder: {output_dir}")

    success_count = 0
    error_count = 0
    skipped_na_count = 0
    skipped_already_y_count = 0

    for index, pub in enumerate(publishers, start=1):
        pub_id = pub.get("publisher_id", "unknown_publisher")
        review_url = pub.get("review_url")

        print(f"\n--- [{index}/{len(publishers)}] {pub_id} ---")

        # Skip if URL is NA
        if not review_url or review_url == "NA":
            print("[SKIP] No valid URL found (NA).")
            skipped_na_count += 1
            continue

        # Skip if already marked successful
        is_successful = pub.get("webpage_extraction_successful")
        if str(is_successful).upper() == "Y":
            print("[SKIP] Already successfully extracted ('Y').")
            skipped_already_y_count += 1
            continue

        output_file_name = f"webpage_{pub_id}_{movie_slug}.html"
        output_file_path = os.path.join(output_dir, output_file_name)

        print(f"[FETCH] URL: {review_url}")
        html_content = None

        # Primary Attempt: Playwright
        try:
            page = context.new_page()
            # Block heavy assets to speed up downloading
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,css}", lambda route: route.abort())

            page.goto(review_url, wait_until="commit", timeout=25000)
            page.wait_for_timeout(2000)

            temp_content = page.content()
            page.close()

            if len(temp_content) >= MIN_VALID_HTML_BYTES:
                html_content = temp_content
            else:
                print(f"[WARNING] Playwright payload too small ({len(temp_content)} chars).")
        except Exception as e:
            print(f"[WARNING] Playwright attempt failed: {e}")

        # Secondary Attempt: Fallback HTTP Downloader
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

        # Save back to the EXACT JSON file dynamically after each publisher
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        time.sleep(2) # Brief pause between requests

    print(f"\n-> [{movie_slug}] FINISHED: Success: {success_count} | Error: {error_count} | Skip(NA): {skipped_na_count} | Skip(Y): {skipped_already_y_count}")

def main():
    print("[STEP 1] Scanning for review JSON files...")

    # Automatically find every JSON file in the reviews folder
    target_files = glob.glob("data/reviews/reviews_*.json")

    # If you ONLY want to process movies based on a master list in `data/movies/`, 
    # you can filter `target_files` here. But scanning `data/reviews/` ensures 
    # we process every movie that currently has a reviews JSON generated.
    
    if not target_files:
        print("[ERROR] No JSON files found in data/reviews/ directory.")
        return

    print(f"[INFO] Found {len(target_files)} movie(s) to process.")

    print("\n[STEP 2] Launching headless browser (Shared across all movies)...")
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=HTTP_HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Referer": "https://www.google.com/"},
        )

        # Loop through every movie found
        for json_path in target_files:
            process_single_movie(json_path, context)

        browser.close()
    
    print("\n" + "=" * 40)
    print("ALL MOVIES BATCH DOWNLOAD COMPLETE")
    print("=" * 40)

if __name__ == "__main__":
    main()
