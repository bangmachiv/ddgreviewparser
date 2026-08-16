import json
import os
import time
import glob
import requests
from playwright.sync_api import sync_playwright
# Use the modern v2.x import
from playwright_stealth import Stealth 

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
MIN_VALID_HTML_BYTES = 2000  # HTML smaller than this is treated as a WAF block

# Richer, more authentic headers for the fallback
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Referer": "https://www.google.com/",
}

def is_valid_html(html_content):
    """Checks if the HTML is an actual article, or just a Cloudflare/Akamai bot challenge."""
    if not html_content or len(html_content) < MIN_VALID_HTML_BYTES:
        return False
        
    lower_html = html_content.lower()
    
    # Common WAF / Bot-Challenge signatures
    bad_signatures = [
        "<title>just a moment...</title>",
        "<title>attention required!</title>",
        "enable javascript and cookies to continue",
        "please verify you are a human",
        "challenge-platform"
    ]
    
    for sig in bad_signatures:
        if sig in lower_html:
            return False
            
    return True

def fallback_download(url):
    """Fallback HTTP fetcher using a Session block for better connection persistence."""
    print("    └─► [FALLBACK] Attempting direct HTTP request...")
    try:
        session = requests.Session()
        session.headers.update(HTTP_HEADERS)
        response = session.get(url, timeout=20)
        
        if response.status_code == 200 and is_valid_html(response.text):
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

    movie_slug = data.get("movie", {}).get("slug")
    
    if not movie_slug:
        print(f"[ERROR] Could not find 'slug' inside {json_path}. Skipping.")
        return

    output_dir = f"data/webpages/html_{movie_slug}"
    os.makedirs(output_dir, exist_ok=True)
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

        if not review_url or review_url == "NA":
            print("[SKIP] No valid URL found (NA).")
            skipped_na_count += 1
            continue

        is_successful = pub.get("webpage_extraction_successful")
        if str(is_successful).upper() == "Y":
            print("[SKIP] Already successfully extracted ('Y').")
            skipped_already_y_count += 1
            continue

        output_file_name = f"webpage_{pub_id}_{movie_slug}.html"
        output_file_path = os.path.join(output_dir, output_file_name)

        print(f"[FETCH] URL: {review_url}")
        html_content = None

        # Primary Attempt: Playwright with Stealth
        try:
            page = context.new_page()
            
            # Advanced Interceptor: Block media/ads but LEAVE scripts needed for bot verification
            def intercept_route(route):
                request = route.request
                resource_type = request.resource_type
                url = request.url.lower()
                
                if resource_type in ["image", "media", "font", "stylesheet"]:
                    route.abort()
                elif any(ad in url for ad in ["doubleclick", "google-analytics", "taboola", "outbrain", "facebook"]):
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", intercept_route)

            page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
            
            # INCREASED WAIT: Give Cloudflare/Akamai 5 seconds to solve the JS challenge
            page.wait_for_timeout(5000)

            temp_content = page.content()
            page.close()

            # Verify it's not a challenge page
            if is_valid_html(temp_content):
                html_content = temp_content
            else:
                print(f"[WARNING] Playwright payload rejected (Likely a bot-challenge page).")
        except Exception as e:
            print(f"[WARNING] Playwright attempt failed: {e}")

        # Secondary Attempt: Fallback
        if not html_content:
            html_content = fallback_download(review_url)

        # Evaluate Final Output
        if html_content:
            print(f"[SUCCESS] Saved {len(html_content)} chars to {output_file_name}")
            with open(output_file_path, "w", encoding="utf-8") as out_file:
                out_file.write(html_content)

            pub["webpage_extraction_successful"] = "Y"
            success_count += 1
        else:
            print(f"[ERROR] Could not extract valid HTML for {pub_id}")
            pub["webpage_extraction_successful"] = "N"
            error_count += 1

        # Save back to JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        time.sleep(2)

    print(f"\n-> [{movie_slug}] FINISHED: Success: {success_count} | Error: {error_count} | Skip(NA): {skipped_na_count} | Skip(Y): {skipped_already_y_count}")

def main():
    print("[STEP 1] Scanning for review JSON files...")

    target_files = glob.glob("data/reviews/reviews_*.json")
    
    if not target_files:
        print("[ERROR] No JSON files found in data/reviews/ directory.")
        return

    print(f"[INFO] Found {len(target_files)} movie(s) to process.")

    print("\n[STEP 2] Launching headless browser (Shared across all movies)...")
    
    # NEW v2.x STEALTH METHOD: Wraps the entire sync_playwright() block
    with Stealth().use_sync(sync_playwright()) as p:
        # THE MAGIC FLAG: Disables the "webdriver" flag Chrome sends to servers
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        
        context = browser.new_context(
            user_agent=HTTP_HEADERS["User-Agent"],
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Referer": "https://www.google.com/"},
            locale="en-IN", # Set locale to India to appear more authentic to HT/IE
            timezone_id="Asia/Kolkata" 
        )

        for json_path in target_files:
            process_single_movie(json_path, context)

        browser.close()
    
    print("\n" + "=" * 40)
    print("ALL MOVIES BATCH DOWNLOAD COMPLETE")
    print("=" * 40)

if __name__ == "__main__":
    main()
