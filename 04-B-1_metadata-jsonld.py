#!/usr/bin/env python3
"""
04-B-1_metadata-jsonld.py
Locally parses downloaded HTML files using Playwright to extract JSON-LD data.
Strictly deterministic (No AI).
"""

import builtins
import json
import os
import glob
from datetime import datetime
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Global Print Override for Real-Time CI/CD Streaming
# ---------------------------------------------------------------------------
def print(*args, **kwargs):
    kwargs['flush'] = True
    builtins.print(*args, **kwargs)

# ---------------------------------------------------------------------------
# Path Configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# STRICT JavaScript extraction logic
# Enforces the parent-child relationship: obj.reviewRating.ratingValue
JS_EXTRACTOR = """
() => {
    const jsonlds = [...document.querySelectorAll('script[type="application/ld+json"]')]
        .map(s => {
            try {
                return JSON.parse(s.textContent);
            } catch {
                return null;
            }
        })
        .filter(Boolean);

    if (jsonlds.length === 0) {
        return { error: "No JSON-LD found" };
    }

    let results = {
        critic_names: [],
        star_ratings: []
    };

    function search(obj) {
        if (!obj || typeof obj !== "object") return;

        // 1. Look for Author/Critic variants (author, reviewer, creator)
        ['author', 'reviewer', 'creator'].forEach(key => {
            if (obj[key]) {
                let persons = Array.isArray(obj[key]) ? obj[key] : [obj[key]];
                persons.forEach(p => {
                    if (p && typeof p === "object" && p.name) {
                        results.critic_names.push(p.name);
                    } else if (typeof p === "string") {
                        results.critic_names.push(p);
                    }
                });
            }
        });

        // 2. STRICT Parent-Child Check: reviewRating -> ratingValue
        if (
            obj.reviewRating && 
            typeof obj.reviewRating === "object" && 
            obj.reviewRating.ratingValue !== undefined
        ) {
            results.star_ratings.push(String(obj.reviewRating.ratingValue));
        }

        // Keep digging recursively through the object
        Object.values(obj).forEach(val => {
            if (val && typeof val === "object") {
                search(val);
            }
        });
    }

    jsonlds.forEach(data => {
        search(data);
    });

    return results;
}
"""

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

# ---------------------------------------------------------------------------
# Pipeline Execution
# ---------------------------------------------------------------------------
def get_live_movie_slugs():
    slugs = []
    live_master_file = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")

    if os.path.exists(live_master_file):
        print(f"[INFO] Reading live movies from master file: {live_master_file}")
        with open(live_master_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            movie_list = data if isinstance(data, list) else data.get("movies", [])
            for movie in movie_list:
                if isinstance(movie, dict) and "slug" in movie:
                    slugs.append(movie["slug"])
    else:
        print(f"[INFO] {live_master_file} not found. Scanning individual files in data/movies/...")
        for file_path in glob.glob(os.path.join(BASE_DIR, "data", "movies", "*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    slug = data.get("slug") or data.get("movie", {}).get("slug")
                    if slug:
                        slugs.append(slug)
                except Exception as e:
                    print(f"[WARNING] Could not read slug from {file_path}: {e}")

    return list(set(slugs))


def is_downloaded_successfully(pub_dict):
    """Helper to permissively check if the webpage was downloaded."""
    val = pub_dict.get("webpage_extraction_successful", pub_dict.get("is_downloaded"))
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().upper() in ["Y", "YES", "TRUE", "SUCCESS"]
    return False


def process_single_movie_json(json_path, context):
    print("\n" + "="*80)
    print(f" PROCESSING LIVE MOVIE FILE: {os.path.basename(json_path)}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_slug = data.get("movie", {}).get("slug")
    if not movie_slug:
        print(f"[ERROR] Could not find 'slug' inside {json_path}. Skipping.")
        return

    # ROBUST DIRECTORY HUNTING: Check multiple common folder structures
    possible_html_dirs = [
        os.path.join(BASE_DIR, f"data/webpages/html_{movie_slug}"),
        os.path.join(BASE_DIR, f"data/webpages/{movie_slug}"),
        os.path.join(BASE_DIR, "data/webpages")
    ]

    html_dir = None
    for directory in possible_html_dirs:
        if os.path.exists(directory):
            html_dir = directory
            break

    if not html_dir:
        print(f"[WARNING] HTML directory not found. Checked: {possible_html_dirs}")
        print("[WARNING] Are your HTML files committed to GitHub, or blocked by a .gitignore?")
        return

    print(f"[INFO] Found HTML directory at: {html_dir}")
    publishers = data.get("publishers", [])

    # Structured Logging Setup
    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "04-B-1_metadata-jsonld.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    valid_statuses = [
        "no data found",
        "both data found",
        "one data found (star rating)",
        "one data found (critic name)"
    ]

    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        current_status = str(pub.get("json_ld_extraction_status", "")).strip()
        review_url = pub.get("review_url")
        
        # Only count valid eligible publishers for pending/completed tracker
        if review_url and review_url != "NA" and is_downloaded_successfully(pub):
            if current_status in valid_statuses:
                earlier_completed += 1
            else:
                earlier_pending += 1

    tracker = PipelineTracker("JSON-LD Evaluation (Playwright)", earlier_completed, earlier_pending)

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

    summary_counts = {
        "Skipped (URL missing)": 0,
        "Skipped (Webpage missing)": 0,
        "Skipped (Already successfully parsed)": 0,
        "no data found": 0,
        "one data found (critic name)": 0,
        "one data found (star rating)": 0,
        "both data found": 0,
        "Error during parsing": 0
    }

    for index, pub in enumerate(publishers, start=1):
        pub_id = pub.get("publisher_id")
        review_url = pub.get("review_url")
        current_status = str(pub.get("json_ld_extraction_status", "")).strip()

        print(f"\n  [{index}/{len(publishers)}] Processing [{pub_id}]...")

        # 1. SKIP CHECK: Already parsed successfully
        if current_status in valid_statuses:
            print(f"      [SKIP] Already parsed: '{current_status}'")
            summary_counts["Skipped (Already successfully parsed)"] += 1
            continue

        # 2. SKIP CHECK: No URL
        if not review_url or review_url == "NA":
            print("      [SKIP] URL missing (NA)")
            summary_counts["Skipped (URL missing)"] += 1
            continue

        # 3. SKIP CHECK: Webpage not downloaded
        if not is_downloaded_successfully(pub):
            status_val = pub.get("webpage_extraction_successful", pub.get("is_downloaded", "Missing Key"))
            print(f"      [SKIP] Webpage missing (JSON value: '{status_val}')")
            summary_counts["Skipped (Webpage missing)"] += 1
            continue

        # 4. VERIFY HTML EXISTS ON DISK
        html_file_name = f"webpage_{pub_id}_{movie_slug}.html"
        html_file_path = os.path.join(html_dir, html_file_name)

        if not os.path.exists(html_file_path):
            alt_file_path = os.path.join(html_dir, f"webpage_{pub_id}.html")
            if os.path.exists(alt_file_path):
                html_file_path = alt_file_path
            else:
                print(f"      [SKIP] HTML file '{html_file_name}' not found on disk in {html_dir}")
                summary_counts["Skipped (Webpage missing)"] += 1
                movie_log_entry["publisher_details"][pub_id] = {"status": "SKIPPED", "reason": "HTML file missing"}
                continue

        # 5. EXECUTE HTML PARSING VIA PLAYWRIGHT
        movie_log_entry["processed"] += 1
        try:
            page = context.new_page()
            file_url = f"file://{os.path.abspath(html_file_path)}"

            page.goto(file_url, wait_until="domcontentloaded", timeout=15000)
            extracted_data = page.evaluate(JS_EXTRACTOR)
            page.close()

            if "error" in extracted_data:
                status_msg = "no data found"
                pub["critic_name"] = "could not find from jsonld"
                pub["star_rating"] = "could not find from jsonld"
            else:
                critic_names = list(dict.fromkeys(extracted_data.get("critic_names", [])))
                star_ratings = list(dict.fromkeys(extracted_data.get("star_ratings", [])))

                has_critic = len(critic_names) > 0
                has_rating = len(star_ratings) > 0

                pub["critic_name"] = critic_names[0] if has_critic else "could not find from jsonld"
                pub["star_rating"] = star_ratings[0] if has_rating else "could not find from jsonld"

                if has_critic and has_rating:
                    status_msg = "both data found"
                elif has_rating and not has_critic:
                    status_msg = "one data found (star rating)"
                elif has_critic and not has_rating:
                    status_msg = "one data found (critic name)"
                else:
                    status_msg = "no data found"

            pub["json_ld_extraction_status"] = status_msg
            print(f"      [SUCCESS] Extraction completed -> {status_msg}")

            tracker.add_success()
            summary_counts[status_msg] += 1
            movie_log_entry["success"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "SUCCESS",
                "json_ld_extraction_status": status_msg,
                "critic_name": pub["critic_name"],
                "star_rating": pub["star_rating"]
            }

        except Exception as e:
            print(f"      [FAILED] Error during parsing: {e}")
            tracker.add_failure()
            summary_counts["Error during parsing"] += 1
            movie_log_entry["failure"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "FAILED",
                "reason": str(e)
            }

    # Save updated JSON state back to the exact target file
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Could not save updated review file: {e}")

    # Log Saving Routine
    movie_log_entry["new_completed"] = earlier_completed + movie_log_entry["success"]
    movie_log_entry["new_pending"] = earlier_pending - movie_log_entry["success"]

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


def parse_all_live_movies():
    print("[STEP 1] Fetching list of LIVE movies...")
    live_slugs = get_live_movie_slugs()

    if not live_slugs:
        print("[ERROR] No live movies found in data/movies/. Exiting.")
        return

    print(f"[INFO] Found {len(live_slugs)} live movie(s) to process: {', '.join(live_slugs)}")

    target_files = []
    for slug in live_slugs:
        review_file = os.path.join(BASE_DIR, "data", "reviews", f"reviews_{slug}.json")
        if os.path.exists(review_file):
            target_files.append(review_file)
        else:
            print(f"[WARNING] Review file missing for live movie: {review_file}")

    if not target_files:
        print("[ERROR] None of the live movies have corresponding review JSON files. Exiting.")
        return

    print("\n[STEP 2] Launching headless browser for JSON-LD Evaluation...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Block external network requests to keep loading instant
        context.route("**/*", lambda route: route.abort() if route.request.url.startswith("http") else route.continue_())

        for json_path in target_files:
            process_single_movie_json(json_path, context)

        browser.close()

    print("\n" + "="*40)
    print("ALL LIVE MOVIES JSON-LD PARSING COMPLETE")
    print("="*40)


if __name__ == "__main__":
    parse_all_live_movies()
