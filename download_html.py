import json
import os
import time
import glob
import urllib.parse
# Import curl_cffi to spoof TLS fingerprints against Cloudflare/Akamai 403s
from curl_cffi import requests as cffi_requests
import requests as standard_requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth 

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
MIN_VALID_HTML_BYTES = 2000  # HTML smaller than this is treated as a WAF block
SCRAPE_DO_TOKEN = os.environ.get("SCRAPE_DO_TOKEN")

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
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
        "challenge-platform",
        "verify you are human"
    ]
    
    for sig in bad_signatures:
        if sig in lower_html:
            return False
            
    return True

def fallback_download(url):
    """Fallback Tier 2: HTTP fetcher using curl_cffi to spoof Chrome TLS fingerprints."""
    print("    └─► [TIER 2 FALLBACK] Attempting TLS-Spoofed HTTP request...")
    try:
        # impersonate="chrome120" mimics a real Chrome browser's raw network signature
        session = cffi_requests.Session(impersonate="chrome120")
        session.headers.update(HTTP_HEADERS)
        response = session.get(url, timeout=20)
        
        if response.status_code == 200 and is_valid_html(response.text):
            print(f"    └─► [TIER 2 SUCCESS] Received {len(response.text)} characters.")
            return response.text
        else:
            print(f"    └─► [TIER 2 FAILED] Status: {response.status_code}, Length: {len(response.text)}")
            return None
    except Exception as e:
        print(f"    └─► [TIER 2 ERROR] {e}")
        return None

def scrape_do_fallback(target_url):
    """Fallback Tier 3: Residential Proxy API via Scrape.do to bypass IP blocks."""
    print("    └─► [TIER 3 FALLBACK] Routing request through Scrape.do API...")
    
    if not SCRAPE_DO_TOKEN:
        print("    └─► [TIER 3 ERROR] SCRAPE_DO_TOKEN environment variable is missing in GitHub Actions!")
        return None

    # URL encode the link so it doesn't break the API request structure
    encoded_url = urllib.parse.quote(target_url)
    
    # Passing &render=true so Scrape.do waits for JS bot challenges to pass
    api_url = f"http://api.scrape.do/?token={SCRAPE_DO_TOKEN}&url={encoded_url}&render=true"
    
    try:
        # We increase timeout to 45s because routing through proxies + rendering heavy JS takes time
        response = standard_requests.get(api_url, timeout=45)
        
        if response.status_code == 200 and is_valid_html(response.text):
            print(f"    └─► [TIER 3 SUCCESS] Received {len(response.text)} characters via Scrape.do.")
            return response.text
        else:
            print(f"    └─► [TIER 3 FAILED] Status: {response.status_code}")
            if response.status_code == 401:
                print("    └─► [TIER 3 FATAL] Invalid API Token or Scrape.do Credits Exhausted.")
            return None
            
    except Exception as e:
        print(f"    └─► [TIER 3 ERROR] {e}")
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

        # BUILD PATH FIRST to verify physical file existence
        output_file_name = f"webpage_{pub_id}_{movie_slug}.html"
        output_file_path = os.path.join(output_dir, output_file_name)

        is_successful = pub.get("webpage_extraction_successful")
        if str(is_successful).upper() == "Y":
            if os.path.exists(output_file_path):
                print("[SKIP] Already successfully extracted ('Y') and file exists.")
                skipped_already_y_count += 1
                continue
            else:
                print(f"[RECOVERY] JSON says 'Y' but {output_file_name} is missing on disk. Forcing re-download.")

        print(f"[FETCH] URL: {review_url}")
        html_content = None

        # TIER 1: Primary Attempt (Playwright with Stealth)
        try:
            page = context.new_page()
            
            # Note: Network interception (blocking images/css) is removed!
            # Cloudflare checks if images load to verify if you are a real browser.

            page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
            
            # INCREASED WAIT: Give Cloudflare/Akamai 8 seconds to solve the JS challenge
            page.wait_for_timeout(8000)

            temp_content = page.content()
            page.close()

            # Verify it's not a challenge page
            if is_valid_html(temp_content):
                html_content = temp_content
            else:
                print(f"[WARNING] Playwright payload rejected (Likely a bot-challenge page).")
        except Exception as e:
            print(f"[WARNING] Playwright attempt failed: {e}")

        # TIER 2: Secondary Attempt (curl_cffi)
        if not html_content:
            html_content = fallback_download(review_url)
            
        # TIER 3: The Final Anti-IP-Ban Fallback (Scrape.do API)
        if not html_content:
            html_content = scrape_do_fallback(review_url)

        # Evaluate Final Output
        if html_content:
            print(f"[SUCCESS] Saved {len(html_content)} chars to {output_file_name}")
            with open(output_file_path, "w", encoding="utf-8") as out_file:
                out_file.write(html_content)

            pub["webpage_extraction_successful"] = "Y"
            success_count += 1
        else:
            print(f"[ERROR] Could not extract valid HTML for {pub_id} across all 3 tiers.")
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
    
    with Stealth().use_sync(sync_playwright()) as p:
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
            locale="en-IN", 
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
