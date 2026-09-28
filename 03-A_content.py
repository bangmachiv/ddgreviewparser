#!/usr/bin/env python3
"""
03a_content.py
Extracts clean article text from downloaded HTML files using BeautifulSoup.
Strictly processes publishers identified via the AI semantic step (classified_by == "AI")
where the HTML download was successful. Outputs to data/webcontent/{slug}/.
"""

import os
import json
import glob
from bs4 import BeautifulSoup
from datetime import datetime

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
WEBPAGES_DIR = os.path.join(BASE_DIR, "data", "webpages")
WEBCONTENT_DIR = os.path.join(BASE_DIR, "data", "webcontent")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# -----------------------------------------------------------------------------
# Pipeline Metric Tracker
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

# -----------------------------------------------------------------------------
# Core Extraction Logic
# -----------------------------------------------------------------------------
def extract_article_text(html_content: str) -> str:
    """Uses BeautifulSoup to strip scripts, styles, and extract the raw text."""
    if not html_content:
        return ""
        
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Remove all script and style elements
    for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
        script.extract()

    # Get text
    text = soup.get_text(separator=' ')
    
    # Clean up whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = '\n'.join(chunk for chunk in chunks if chunk)
    
    return text

def process_single_movie(json_path: str):
    """Processes extraction for a single movie's JSON file."""
    print("\n" + "=" * 80)
    print(f" TEXT EXTRACTION FOR: {json_path}")
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

    # Set up Directories
    html_dir = os.path.join(WEBPAGES_DIR, movie_slug)
    content_dir = os.path.join(WEBCONTENT_DIR, movie_slug)
    os.makedirs(content_dir, exist_ok=True)

    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
    script_log_path = os.path.join(movie_logs_dir, "03a_content.json")
    os.makedirs(movie_logs_dir, exist_ok=True)

    publishers = data.get("publishers", [])

    # Pre-Scan Metrics
    earlier_completed = 0
    earlier_pending = 0

    for pub in publishers:
        if pub.get("classified_by") == "AI" and pub.get("webpage_extraction_successful") == "SUCCESS":
            pub_id = pub.get("publisher_id")
            content_file = os.path.join(content_dir, f"content_{pub_id}_{movie_slug}.txt")
            if os.path.exists(content_file):
                earlier_completed += 1
            else:
                earlier_pending += 1

    tracker = PipelineTracker("Text Extracted (AI Classified)", earlier_completed, earlier_pending)

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

    for pub in publishers:
        pub_id = pub.get("publisher_id")
        pub_name = pub.get("publisher_name")
        classified_by = pub.get("classified_by")
        download_status = pub.get("webpage_extraction_successful")

        # Execution Gate: Must be AI classified and successfully downloaded
        if classified_by != "AI" or download_status != "SUCCESS":
            continue
            
        html_file = os.path.join(html_dir, f"webpage_{pub_id}_{movie_slug}.html")
        content_file = os.path.join(content_dir, f"content_{pub_id}_{movie_slug}.txt")

        # Skip if already extracted
        if os.path.exists(content_file):
            print(f"  [SKIP] {pub_name} already extracted.")
            continue
            
        if not os.path.exists(html_file):
            print(f"  [WARNING] HTML missing for {pub_name}, despite SUCCESS status. Skipping.")
            continue
            
        print(f"\n--- Extracting {pub_name} ---")
        movie_log_entry["processed"] += 1
        
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                html_content = f.read()
                
            raw_text = extract_article_text(html_content)
            
            if len(raw_text) > 500: # Ensure we got actual article content, not just a broken page
                with open(content_file, "w", encoding="utf-8") as f:
                    f.write(raw_text)
                    
                print(f"  [SUCCESS] Saved {len(raw_text)} text characters.")
                tracker.add_success()
                movie_log_entry["success"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": "SUCCESS",
                    "file": f"content_{pub_id}_{movie_slug}.txt",
                    "characters": len(raw_text)
                }
            else:
                print(f"  [FAILED] Extracted text too short ({len(raw_text)} chars). Likely parsing error.")
                tracker.add_failure()
                movie_log_entry["failure"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": "FAILED",
                    "reason": "Text payload too short."
                }
                
        except Exception as e:
            print(f"  [ERROR] Failed to process {pub_name}: {e}")
            tracker.add_failure()
            movie_log_entry["failure"] += 1
            movie_log_entry["publisher_details"][pub_id] = {
                "status": "FAILED",
                "reason": str(e)
            }

    # Finalize Log
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

def main():
    target_files = glob.glob(os.path.join(REVIEWS_DIR, "reviews_*.json"))

    if not target_files:
        print("[ERROR] No JSON files found in data/reviews/ directory.")
        return

    print(f"[INFO] Found {len(target_files)} movie review file(s) for extraction.")

    for json_path in target_files:
        process_single_movie(json_path)

    print("\n" + "=" * 40)
    print(" ALL TEXT EXTRACTIONS COMPLETED")
    print("=" * 40)

if __name__ == "__main__":
    main()
