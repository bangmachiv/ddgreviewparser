#!/usr/bin/env python3
"""
03_download.py
"""

import os
import sys
import json
import time
import glob
import urllib.parse
from datetime import datetime

# TLS Fingerprint spoofing & Browser Automations
from curl_cffi import requests as cffi_requests
import requests as standard_requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
WEBPAGES_DIR = os.path.join(BASE_DIR, "data", "webpages")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

MIN_VALID_HTML_BYTES = 2000  # HTML smaller than this is treated as a WAF block
SCRAPE_DO_TOKEN = os.environ.get("SCRAPE_DO_TOKEN")

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}

# -----------------------------------------------------------------------------
# 7-Column Pipeline Metric Tracker
# -----------------------------------------------------------------------------
class PipelineTracker:
    def __init__(self, metric_name, earlier_completed, earlier_pending):
        self.metric_name = metric_name
        self.earlier_completed = earlier_completed
        self.earlier_pending = earlier_pending
        self.processed = 0
        self.succeeded = 0
        self.failed = 0

    def add_success(self, count=1):
        self.processed += count
        self.succeeded += count

    def add_failure(self, count=1):
        self.processed += count
        self.failed += count

    def print_summary(self):
        new_completed = self.earlier_completed + self.succeeded
        new_pending = self.earlier_pending - self.succeeded

        print("\n" + "=" * 125)
        print(f" PIPELINE METRIC: {self.metric_name}")
        print("=" * 125)
        print(f"| {'Earlier Completed':^17} | {'Earlier Pending':^15} | {'Processed':^9} | {'Success':^7} | {'Failure':^7} | {'New Completed':^13} | {'New Pending':^11} |")
        print("-" * 125)
        print(f"| {self.earlier_completed:^17} | {self.earlier_pending:^15} | {self.processed:^9} | {self.succeeded:^7} | {self.failed:^7} | {new_completed:^13} | {new_pending:^11} |")
        print("=" * 125 + "\n")


def is_valid_html(html_content: str) -> bool:
    """Checks if the HTML is an actual article or a bot challenge/block page."""
    if not html_content or len(html_content) < MIN_VALID_HTML_BYTES:
        return False

    # Challenge pages are typically small; real articles are large
    if len(html_content) > 80000:
        return True

    lower_html = html_content.lower()

    bad_titles = [
        "<title>just a moment...</title>",
        "<title>attention required!</title>",
        "<title>security challenge</title>"
    ]

    for title in bad_titles:
        if title in lower_html:
            return False

    bad_signatures = [
        "enable javascript and cookies to continue",
        "please verify you are a human",
        "challenge-platform"
    ]

    for sig in bad_signatures:
        if sig in lower_html:
            return False

    return True


def fallback_download(url: str):
    """Fallback Tier 2: HTTP fetcher using curl_cffi to spoof Chrome TLS fingerprints."""
    print("    └─► [TIER 2 FALLBACK] Attempting TLS-Spoofed HTTP request...")
    try:
        session = cffi_requests.Session(impersonate="chrome120")
        session.headers.update(HTTP_HEADERS)
        response = session.get(url, timeout=20)

        if response.status_code == 200 and is_valid_html(response.text):
            print(f"    └─► [TIER 2 SUCCESS] Received {len(response.text)} characters.")
            return response.text
        else:
            print(f"    └─► [TIER 2 FAILED] Status: {response.status_code}, Length: {len(response.text) if response.text else 0}")
            return None
    except Exception as e:
        print(f"    └─► [TIER 2 ERROR] {e}")
        return None


def scrape_do_fallback(target_url: str):
    """Fallback Tier 3: Residential Proxy API via Scrape.do."""
    print("    └─► [TIER 3 FALLBACK] Routing request through Scrape.do API...")

    if not SCRAPE_DO_TOKEN:
        print("    └─► [TIER 3 ERROR] SCRAPE_DO_TOKEN environment variable is not set!")
        return None

    encoded_url = urllib.parse.quote(target_url)
    api_url = f"http://api.scrape.do/?token={SCRAPE_DO_TOKEN}&url={encoded_url}&render=true&super=true&geoCode=in"

    try:
        response = standard_requests.get(api_url, timeout=60)
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


def process_single_movie(json_path: str, context):
    """Processes a single movie's reviews JSON file."""
    print("\n" + "=" * 80)
    print(f" LOADING TARGET: {json_path}")
    print("=" * 80)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] Could not read {json_path}: {e}")
        return

    movie_slug = data.get("movie", {}).get("slug")
    if not movie_slug:
        print(f"[ERROR] Missing 'slug' in {json_path}. Skipping.")
        return

    output_dir = os.path.join(WEBPAGES_DIR, movie_slug)
    os.makedirs(output_dir, exist_ok=True)

    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "03_download.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    publishers = data.get("publishers", [])

    # -------------------------------------------------------------------------
    # Pre-Scan Metrics Calculation
    # -------------------------------------------------------------------------
    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        review_url = pub.get("review_url", "PENDING")
        status = pub.get("webpage_extraction_successful", "PENDING")

        # Only items with an identified URL are candidates for download
        if review_url not in ["PENDING", "NA", ""]:
            if status == "SUCCESS":
                earlier_completed += 1
            else:
                earlier_pending += 1

    tracker = PipelineTracker("Webpages Downloaded", earlier_completed, earlier_pending)

    movie_log_entry = {
        "earlier_completed": earlier_completed,
        "earlier_pending": earlier_pending,
        "processed": 0,
        "success": 0,
        "failure": 0,
        "new_completed": 0,
        "new_pending": 0,
        "publisher_details": {}
    }

    # -------------------------------------------------------------------------
    # Execution Loop
    # -------------------------------------------------------------------------
    for index, pub in enumerate(publishers, start=1):
        pub_id = pub.get("publisher_id", f"publisher_{index}")
        review_url = pub.get("review_url", "PENDING")
        extraction_status = pub.get("webpage_extraction_successful", "PENDING")

        output_file_name = f"webpage_{pub_id}_{movie_slug}.html"
        output_file_path = os.path.join(output_dir, output_file_name)

        # 1. Skip if no review URL has been identified yet
        if review_url in ["PENDING", "NA", ""]:
            continue

        # 2. Skip if already completed and file physically exists on disk
        if extraction_status == "SUCCESS" and os.path.exists(output_file_path):
            print(f"  [{index}/{len(publishers)}] [SKIP] {pub_id} already downloaded.")
            continue

        print(f"\n--- [{index}/{len(publishers)}] Downloading {pub_id} ---")
        print(f"  URL: {review_url}")
        
        movie_log_entry["processed"] += 1
        html_content = None
        used_tier = None

        # TIER 1: Primary Attempt (Playwright + Stealth)
        try:
            page = context.new_page()
            page.goto(review_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(8000)
            temp_content = page.content()
            page.close()

            if is_valid_html(temp_content):
                html_content = temp_content
                used_tier = "Tier 1 (Playwright Stealth)"
            else:
                print("    └─► [WARNING] Tier 1 Playwright payload rejected (Bot challenge page).")
        except Exception as e:
            print(f"    └─► [WARNING] Tier 1 Playwright failed: {e}")

        # TIER 2: TLS Spoofing (curl_cffi)
        if not html_content:
            html_content = fallback_download(review_url)
            if html_content:
                used_tier = "Tier 2 (curl_cffi)"

        # TIER 3: Residential Proxy (Scrape.do)
        if not html_content:
            html_content = scrape_do_fallback(review_url)
            if html_content:
                used_tier = "Tier 3 (Scrape.do)"

        # Save HTML and update publisher record
        if html_content:
            print(f"  [SUCCESS] Saved {len(html_content)} chars to {output_file_name} via {used_tier}")
            with open(output_file_path, "w", encoding="utf-8") as out_file:
                out_file.write(html_content)

            pub["webpage_extraction_successful"] = "SUCCESS"
            tracker.add_success()
            movie_log_entry["success"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "SUCCESS",
                "tier": used_tier,
                "file": output_file_name,
                "bytes": len(html_content)
            }
        else:
            print(f"  [FAILED] Could not download HTML for {pub_id} across all 3 tiers.")
            pub["webpage_extraction_successful"] = "FAILED"
            tracker.add_failure()
            movie_log_entry["failure"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "FAILED",
                "reason": "All 3 tiers failed"
            }

        # Save reviews JSON incrementally
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] Could not save updated review file: {e}")

        time.sleep(2)

    # Finalize log summary
    movie_log_entry["new_completed"] = earlier_completed + movie_log_entry["success"]
    movie_log_entry["new_pending"] = earlier_pending - movie_log_entry["success"]

    # Safely write to 03_download.json
    script_log_data = {}
    if os.path.exists(script_log_path) and os.path.getsize(script_log_path) > 0:
        try:
            with open(script_log_path, "r", encoding="utf-8") as lf:
                script_log_data = json.load(lf)
        except json.JSONDecodeError:
            pass

    timestamp = datetime.now().astimezone().isoformat()
    script_log_data[timestamp] = movie_log_entry

    try:
        with open(script_log_path, "w", encoding="utf-8") as lf:
            json.dump(script_log_data, lf, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[ERROR] Could not write to log file: {e}")

    tracker.print_summary()


def main():
    target_files = glob.glob(os.path.join(REVIEWS_DIR, "reviews_*.json"))

    if not target_files:
        print("[ERROR] No JSON files found in data/reviews/ directory.")
        return

    print(f"[INFO] Found {len(target_files)} movie review file(s) to process.")

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
    print(" ALL DOWNLOAD RUNS COMPLETED")
    print("=" * 40)


if __name__ == "__main__":
    main()
