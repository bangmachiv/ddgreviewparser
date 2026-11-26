#!/usr/bin/env python3
"""
02_identify.py
Deterministic search result classifier utilizing strict string compression boundaries.
Filters candidate URLs based on video parameters, negative phrase exclusions, 
and exact-match compressed permutations of the movie title and review identifiers.
Updates the 6-field state machine for the pipeline.
"""

import os
import json
import re
from urllib.parse import urlparse, parse_qs
from datetime import datetime

# ============================================================
# CONFIGURATION
# ============================================================
REVIEW_PHRASES = [
    "review", "movie review", "film review", "hindi review",
    "hindi movie review", "रिव्यू", "समीक्षा", "मूवी रिव्यू",
    "मूवी समीक्षा", "फिल्म रिव्यू", "फिल्म समीक्षा", "हिंदी रिव्यू"
]

NEGATIVE_PHRASES = [
    "compilation", "roundup", "video", "podcast", "twitter", "reddit",
    "explained", "ending explained", "ending", "analysis", "breakdown",
    "box office", "collection", "trailer", "teaser", "cast", "songs",
    "soundtrack", "ott", "streaming", "preview", "first look", "featurette",
    "reaction", "reactions", "live updates"
]

# -----------------------------------------------------------------------------
# Custom Metric Tracker
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
        print("\n" + "="*125)
        print(f" PIPELINE METRIC: {self.metric_name}")
        print("="*125)
        print(f"| {'Earlier Completed':^17} | {'Earlier Pending':^15} | {'Processed':^9} | {'Success':^7} | {'Failure':^7} | {'New Completed':^13} | {'New Pending':^11} |")
        print("-" * 125)
        print(f"| {self.earlier_completed:^17} | {self.earlier_pending:^15} | {self.processed:^9} | {self.succeeded:^7} | {self.failed:^7} | {new_completed:^13} | {new_pending:^11} |")
        print("="*125 + "\n")

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def is_video_url(url: str) -> bool:
    if not url: return False
    url_lower = url.lower()
    parsed = urlparse(url_lower)
    if "/video/" in parsed.path or parsed.path.rstrip("/").endswith("/video"):
        return True
    if "video" in parse_qs(parsed.query).get("type", []):
        return True
    return False

def compress_string(text: str) -> str:
    """
    Compresses a string by removing all spaces and special characters.
    Natively preserves Unicode letters (like Hindi/Devanagari).
    """
    if not text: return ""
    return re.sub(r'[^\w]', '', str(text)).lower()

def check_if_review(raw_title: str, raw_url: str, search_titles_array: list) -> bool:
    """
    Evaluates if a title qualifies as a review using exact compressed combinations
    anchored to the start or end of the compressed target string to prevent
    substring merging false positives (e.g. 'raaz' inside 'aura aziz').
    """
    if not raw_title or not raw_url:
        return False

    # 1. Video URL Check
    if is_video_url(raw_url):
        return False

    # 2. Negative Phrase Check 
    # (Checked against padded raw title so we don't accidentally match substrings)
    title_lower = raw_title.lower()
    padded_title = f" {re.sub(r'[^a-z0-9\s]', ' ', title_lower)} "
    for neg in NEGATIVE_PHRASES:
        if f" {neg} " in padded_title:
            return False

    # 3. Compressed String Boundary Matching
    compressed_target = compress_string(raw_title)

    for movie_name in search_titles_array:
        compressed_movie = compress_string(movie_name)
        
        for phrase in REVIEW_PHRASES:
            compressed_phrase = compress_string(phrase)
            
            # Create the valid combo units
            combo_front = compressed_movie + compressed_phrase
            combo_back = compressed_phrase + compressed_movie

            # The valid combo MUST anchor to either the start or end of the title
            # OR equal the entire title exactly. This completely prevents mid-string 
            # alphanumeric merging false positives.
            if compressed_target.startswith(combo_front) or \
               compressed_target.endswith(combo_front) or \
               compressed_target.startswith(combo_back) or \
               compressed_target.endswith(combo_back) or \
               compressed_target == combo_front or \
               compressed_target == combo_back:
                return True

    return False

# -----------------------------------------------------------------------------
# Main Execution Logic
# -----------------------------------------------------------------------------
def main():
    base = os.path.dirname(os.path.abspath(__file__))
    movies_file = os.path.join(base, "data", "movies", "movies-live-today.json")
    searches_dir = os.path.join(base, "data", "searches")
    reviews_dir = os.path.join(base, "data", "reviews")

    if not os.path.exists(movies_file): return

    with open(movies_file, encoding="utf-8") as f:
        movies_data = json.load(f)
    
    # Safely handle the list vs object structure
    active_movies = movies_data.get("movies", []) if isinstance(movies_data, dict) else movies_data

    for movie in active_movies:
        movie_name = movie.get("name")
        slug = movie.get("slug")
        search_file = os.path.join(searches_dir, f"searches_{slug}.json")
        reviews_file_path = os.path.join(reviews_dir, f"reviews_{slug}.json")

        if not os.path.exists(search_file) or not os.path.exists(reviews_file_path):
            continue

        movie_logs_dir = os.path.join(base, "logs", f"logs_{slug}")
        script_log_path = os.path.join(movie_logs_dir, "02_identify.json")
        os.makedirs(movie_logs_dir, exist_ok=True)

        print(f"\n================================================================================")
        print(f" Parsing Reviews for: {movie['name']}")
        print(f"================================================================================")

        with open(search_file, encoding="utf-8") as f:
            search_data = json.load(f)
        with open(reviews_file_path, "r", encoding="utf-8") as f:
            reviews_data = json.load(f)

        # Retrieve localized name array or fallback to english name
        search_titles_array = movie.get("search_titles", [movie_name])
        
        search_results_map = {pub.get("publisher_id"): pub for pub in search_data.get("publishers", [])}

        earlier_completed = 0
        earlier_pending = 0
        for pub_block in reviews_data.get("publishers", []):
            ru = pub_block.get("review_url", "PENDING")
            if ru not in ["PENDING", "NA", ""]:
                earlier_completed += 1
            else:
                earlier_pending += 1

        tracker = PipelineTracker("Review URLs Identified", earlier_completed, earlier_pending)

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

        for pub_block in reviews_data.get("publishers", []):
            pub_id = pub_block.get("publisher_id", "")
            pub_name = pub_block.get("publisher_name", "")
            ru = pub_block.get("review_url", "PENDING")
            ss = pub_block.get("search_status", "PENDING")
            sc = pub_block.get("search_count", 0)

            if ru not in ["PENDING", "NA", ""]:
                print(f"  [SKIP PARSING] {pub_name} already classified.")
                continue

            if ru in ["PENDING", "NA", ""] and ss == "SUCCESS" and sc > 0:
                print(f"  [EVALUATING] {pub_name}...")
                movie_log_entry["processed"] += 1
                search_pub_data = search_results_map.get(pub_id, {})
                first = None

                for result in search_pub_data.get("results", []):
                    # Uses exact boundary compressed logic against the search array
                    if check_if_review(result.get("title", ""), result.get("url", ""), search_titles_array):
                        if first is None:
                            first = result

                if first:
                    rank = first.get('rank')
                    print(f"    -> [SUCCESS] Found valid review at Rank {rank}")
                    pub_block["review_url"] = first.get("url", "NA")
                    pub_block["review_title"] = first.get("title", "NA")
                    pub_block["review_source"] = f"tavily_{rank}"
                    pub_block["classified_by"] = "SCRIPT"

                    tracker.add_success()
                    movie_log_entry["success"] += 1
                    movie_log_entry["publisher_details"][pub_id] = {
                        "status": "SUCCESS",
                        "source_rank": f"tavily_{rank}"
                    }
                else:
                    print(f"    -> [FAILED] No valid review titles found.")
                    pub_block["search_status"] = "PENDING"

                    tracker.add_failure()
                    movie_log_entry["failure"] += 1
                    movie_log_entry["publisher_details"][pub_id] = {
                        "status": "FAILED",
                        "reason": "No valid titles found"
                    }

        movie_log_entry["new_completed"] = earlier_completed + movie_log_entry["success"]
        movie_log_entry["new_pending"] = earlier_pending - movie_log_entry["success"]

        with open(reviews_file_path, "w", encoding="utf-8") as f:
            json.dump(reviews_data, f, ensure_ascii=False, indent=4)

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

if __name__ == "__main__":
    main()
