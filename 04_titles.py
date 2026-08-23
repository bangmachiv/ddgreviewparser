#!/usr/bin/env python3
"""
04_extract_titles.py
Extracts the <title> tag from downloaded HTML files and updates reviews JSON.
"""

import os
import re
import sys
import json
import glob
from datetime import datetime

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
WEBPAGES_DIR = os.path.join(BASE_DIR, "data", "webpages")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

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


def extract_title_from_html(html_content: str):
    """Extracts and cleans the <title> tag from raw HTML string."""
    match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        raw_title = match.group(1).strip()
        clean_title = " ".join(raw_title.split())
        return clean_title if clean_title else None
    return None


def process_titles_for_movie(json_path: str):
    """Processes title extraction for a single movie review JSON file."""
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

    html_dir = os.path.join(WEBPAGES_DIR, movie_slug)
    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "04_extract_titles.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    publishers = data.get("publishers", [])

    # -------------------------------------------------------------------------
    # Pre-Scan Metrics Calculation
    # -------------------------------------------------------------------------
    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        extraction_status = pub.get("webpage_extraction_successful", "PENDING")
        article_title = pub.get("article_title", "PENDING")

        # Candidates are publishers that have a successfully downloaded HTML page
        if extraction_status == "SUCCESS":
            if article_title not in ["PENDING", None, ""]:
                earlier_completed += 1
            else:
                earlier_pending += 1

    tracker = PipelineTracker("Article Titles Extracted", earlier_completed, earlier_pending)

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
        current_title = pub.get("article_title", "PENDING")

        # 1. Skip if download was not successful or no review URL exists
        if extraction_status != "SUCCESS" or review_url in ["PENDING", "NA", ""]:
            continue

        # 2. Skip if title is already extracted
        if current_title not in ["PENDING", None, ""]:
            print(f"  [{index}/{len(publishers)}] [SKIP] {pub_id} title already extracted.")
            continue

        # Build and check HTML filepath
        html_file_name = f"webpage_{pub_id}_{movie_slug}.html"
        html_file_path = os.path.join(html_dir, html_file_name)

        if not os.path.exists(html_file_path):
            print(f"  [{index}/{len(publishers)}] [WARN] Missing HTML file on disk for {pub_id}. Skipping.")
            continue

        print(f"\n--- [{index}/{len(publishers)}] Parsing {pub_id} ---")
        movie_log_entry["processed"] += 1

        try:
            with open(html_file_path, "r", encoding="utf-8", errors="ignore") as hf:
                html_content = hf.read()

            extracted_title = extract_title_from_html(html_content)

            if extracted_title:
                print(f"  [SUCCESS] Extracted: {extracted_title}")
                pub["article_title"] = extracted_title
                tracker.add_success()
                movie_log_entry["success"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": "SUCCESS",
                    "article_title": extracted_title
                }
            else:
                print(f"  [FAILED] <title> tag not found in {html_file_name}")
                pub["article_title"] = "FAILED"
                tracker.add_failure()
                movie_log_entry["failure"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": "FAILED",
                    "reason": "No <title> tag found"
                }

        except Exception as e:
            print(f"  [ERROR] Failed to read {html_file_path}: {e}")
            pub["article_title"] = "FAILED"
            tracker.add_failure()
            movie_log_entry["failure"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "FAILED",
                "reason": str(e)
            }

        # Save reviews JSON incrementally
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] Could not save updated review file: {e}")

    # Finalize log summary
    movie_log_entry["new_completed"] = earlier_completed + movie_log_entry["success"]
    movie_log_entry["new_pending"] = earlier_pending - movie_log_entry["success"]

    # Safely write to 04_extract_titles.json
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

    for json_path in target_files:
        process_titles_for_movie(json_path)

    print("\n" + "=" * 40)
    print(" ALL TITLE EXTRACTIONS COMPLETED")
    print("=" * 40)


if __name__ == "__main__":
    main()
