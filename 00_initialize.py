#!/usr/bin/env python3

"""
TASK: Initialize master pipeline ledgers, base files, and directory structures for all active movies.

INPUT FILES READ:
  - publishers.json (Root)
  - data/movies/movies-live-today.json

OUTPUT FOLDERS CREATED (Per Movie):
  1. data/webpages/<slugname>/
  2. logs/logs_<slugname>/
  3. logs/logs_<slugname>/pipeline_<slugname>/

OUTPUT FILES GENERATED/UPDATED (Per Movie):
  1. data/searches/searches_<slugname>.json (Initialized as {})
  2. data/reviews/reviews_<slugname>.json
  3. 10 Empty Script Log Files (00_initialize.json to 09_label.json) in logs/logs_<slugname>/

OUTPUT FIELDS WRITTEN (Master Skeleton injected into reviews_<slugname>.json):
  publisher_id, publisher_name, search_needed, search_result_count, review_url, 
  review_title, search_rank, webpage_extraction_successful, article_title, 
  clean_title, highlighted_title, jsonld_critic_name, jsonld_star_rating, 
  ai_metadata_parsing_attempts, ai_critic_name, ai_star_rating, ai_sentiment_category
"""

import json
import os
import sys
from datetime import datetime

# -----------------------------------------------------------------------------
# Configuration & Absolute Pathing for GitHub Actions
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
PUBLISHERS_FILE = os.path.join(BASE_DIR, "publishers.json")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
SEARCHES_DIR = os.path.join(BASE_DIR, "data", "searches")
WEBPAGES_DIR = os.path.join(BASE_DIR, "data", "webpages")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# -----------------------------------------------------------------------------
# 7-Column Metric Tracker Utility
# -----------------------------------------------------------------------------
class PipelineTracker:
    def __init__(self, metric_name, done_before, to_be_done_before):
        self.metric_name = metric_name
        self.done_before = done_before
        self.to_be_done_before = to_be_done_before
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
        done_after = self.done_before + self.succeeded
        to_be_done_after = self.to_be_done_before - self.succeeded

        print("\n" + "="*105)
        print(f" PIPELINE METRIC: {self.metric_name}")
        print("="*105)
        print(f"| {'Done (Bef)':^10} | {'To Be Done (Bef)':^16} | {'Processed':^9} | {'Succeeded':^9} | {'Failed':^6} | {'Done (Aft)':^10} | {'To Be Done (Aft)':^16} |")
        print("-" * 105)
        print(f"| {self.done_before:^10} | {self.to_be_done_before:^16} | {self.processed:^9} | {self.succeeded:^9} | {self.failed:^6} | {done_after:^10} | {to_be_done_after:^16} |")
        print("="*105 + "\n")

# -----------------------------------------------------------------------------
# Main Execution Logic
# -----------------------------------------------------------------------------
def main():
    print("=" * 80)
    print(" PIPELINE STEP 0: INITIALIZE MASTER SKELETONS")
    print("=" * 80)

    # 1. Base Output Directories (Guarantees Write Rights)
    for folder in [REVIEWS_DIR, SEARCHES_DIR, WEBPAGES_DIR, LOGS_DIR]:
        os.makedirs(folder, exist_ok=True)
        # Create a .gitkeep to ensure Git tracks even completely empty base folders
        with open(os.path.join(folder, ".gitkeep"), "w") as f:
            pass
        print(f"[SUCCESS] Base folder verified and locked for Git tracking: {folder}")

    # 2. Load Active Publishers
    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL ERROR] {PUBLISHERS_FILE} not found. Cannot proceed.")
        sys.exit(1)
        
    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        all_publishers = json.load(f)
    
    active_publishers = [p for p in all_publishers if p.get("active", False)]
    print(f"[INFO] Loaded {len(active_publishers)} active publishers.")

    # 3. Load Active Movies
    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL ERROR] {MOVIES_FILE} not found. No movies to process.")
        sys.exit(1)

    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        movies_data = json.load(f)
    
    active_movies = movies_data.get("movies", [])
    print(f"[INFO] Loaded {len(active_movies)} active movies.")

    # -------------------------------------------------------------------------
    # PRE-SCAN: Calculate Metrics (Done Before, To Be Done Before)
    # -------------------------------------------------------------------------
    global_done_before = 0
    global_to_be_done_before = 0

    for movie in active_movies:
        slug = movie.get("slug")
        reviews_path = os.path.join(REVIEWS_DIR, f"reviews_{slug}.json")
        
        if os.path.exists(reviews_path):
            try:
                with open(reviews_path, "r", encoding="utf-8") as rf:
                    existing_data = json.load(rf)
                existing_pub_ids = [p.get("publisher_id") for p in existing_data.get("publishers", [])]
                
                # Count how many active publishers are already in this movie's file
                movie_done = sum(1 for pub in active_publishers if pub["id"] in existing_pub_ids)
                movie_todo = len(active_publishers) - movie_done
                
                global_done_before += movie_done
                global_to_be_done_before += movie_todo
            except Exception:
                # If file is corrupted, all active publishers need to be done
                global_to_be_done_before += len(active_publishers)
        else:
            # File doesn't exist, all active publishers need to be done for this movie
            global_to_be_done_before += len(active_publishers)

    # Initialize the Tracker
    tracker = PipelineTracker("Blocks made in reviews file", global_done_before, global_to_be_done_before)

    # -------------------------------------------------------------------------
    # ACTION RUN: Build Files, Folders, and Skeletons
    # -------------------------------------------------------------------------
    for movie in active_movies:
        movie_name = movie.get("name")
        movie_slug = movie.get("slug")
        movie_date = movie.get("date", "")
        
        print(f"\n[PROCESSING MOVIE] {movie_name} ({movie_slug})")
        
        # A. Create Movie-Specific Folders and force Git to track them
        movie_webpages_dir = os.path.join(WEBPAGES_DIR, movie_slug)
        movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
        movie_pipeline_logs = os.path.join(movie_logs_dir, f"pipeline_{movie_slug}")
        
        try:
            os.makedirs(movie_webpages_dir, exist_ok=True)
            os.makedirs(movie_pipeline_logs, exist_ok=True)
            
            # Create .gitkeep files inside the movie folders
            with open(os.path.join(movie_webpages_dir, ".gitkeep"), "w") as f:
                pass
            with open(os.path.join(movie_pipeline_logs, ".gitkeep"), "w") as f:
                pass
                
            # Create 10 empty JSON log files for all scripts (00 to 09)
            script_logs = [
                "00_initialize.json",
                "01_search.json",
                "02_identify.json",
                "03_download.json",
                "04_title.json",
                "05_clean.json",
                "06_highlight.json",
                "07_metadata.json",
                "08_ai_metadata.json",
                "09_label.json"
            ]
            
            for script_log in script_logs:
                log_path = os.path.join(movie_logs_dir, script_log)
                if not os.path.exists(log_path):
                    with open(log_path, "w", encoding="utf-8") as lf:
                        json.dump({}, lf) # Initialize as an empty JSON object
                        
            print(f"  [SUCCESS] Movie folders and 10 script log files created.")
        except Exception as e:
            print(f"  [FAILED] Could not create folders or log files: {e}")
            
        # B. Initialize Searches file if missing
        searches_path = os.path.join(SEARCHES_DIR, f"searches_{movie_slug}.json")
        if not os.path.exists(searches_path):
            try:
                with open(searches_path, "w", encoding="utf-8") as sf:
                    json.dump({}, sf)
                print(f"  [SUCCESS] Created empty searches_{movie_slug}.json")
            except Exception as e:
                print(f"  [FAILED] Could not create searches file: {e}")

        # C. Load or Create Reviews Master Skeleton
        reviews_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
        
        if os.path.exists(reviews_path):
            try:
                with open(reviews_path, "r", encoding="utf-8") as rf:
                    reviews_data = json.load(rf)
                print(f"  [INFO] Loaded existing reviews_{movie_slug}.json")
            except Exception as e:
                print(f"  [FAILED] Corrupted reviews file: {e}")
                continue
        else:
            reviews_data = {
                "movie": {"name": movie_name, "slug": movie_slug, "date": movie_date},
                "publishers": []
            }
            print(f"  [SUCCESS] Created new reviews base object.")

        # D. Map existing and inject missing
        existing_pubs = {p.get("publisher_id"): p for p in reviews_data.get("publishers", [])}
        blocks_to_add = 0
        
        for pub in active_publishers:
            pub_id = pub["id"]
            if pub_id not in existing_pubs:
                # The 17-field Master Skeleton
                existing_pubs[pub_id] = {
                    "publisher_id": pub_id,
                    "publisher_name": pub["name"],
                    "search_needed": "Y",
                    "search_result_count": "PENDING",
                    "review_url": "PENDING",
                    "review_title": "PENDING",
                    "search_rank": "PENDING",
                    "webpage_extraction_successful": "PENDING",
                    "article_title": "PENDING",
                    "clean_title": "PENDING",
                    "highlighted_title": "PENDING",
                    "jsonld_critic_name": "PENDING",
                    "jsonld_star_rating": "PENDING",
                    "ai_metadata_parsing_attempts": 0,
                    "ai_critic_name": "NOT_NEEDED",
                    "ai_star_rating": "NOT_NEEDED",
                    "ai_sentiment_category": "PENDING"
                }
                blocks_to_add += 1

        # E. Sort alphabetically by publisher_id
        updated_publishers = list(existing_pubs.values())
        updated_publishers.sort(key=lambda x: x["publisher_id"])
        reviews_data["publishers"] = updated_publishers
        
        # F. Save to disk, update tracker, and record script's own log
        save_success = False
        if blocks_to_add > 0:
            try:
                with open(reviews_path, "w", encoding="utf-8") as rf:
                    json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
                print(f"  [SUCCESS] Injected {blocks_to_add} missing publishers into reviews file.")
                tracker.add_success(blocks_to_add)
                save_success = True
            except Exception as e:
                print(f"  [FAILED] Could not save reviews file: {e}")
                tracker.add_failure(blocks_to_add)
        else:
            print(f"  [INFO] No missing publishers to inject for this movie.")
            save_success = True
            
        # G. Self-Logging execution status to 00_initialize.json
        init_log_path = os.path.join(movie_logs_dir, "00_initialize.json")
        try:
            if os.path.exists(init_log_path):
                with open(init_log_path, "r", encoding="utf-8") as lf:
                    init_log = json.load(lf)
            else:
                init_log = {}
                
            timestamp = datetime.now().astimezone().isoformat()
            init_log[timestamp] = {
                "blocks_added": blocks_to_add,
                "total_publishers_active": len(updated_publishers),
                "status": "SUCCESS" if save_success else "FAILED"
            }
            
            with open(init_log_path, "w", encoding="utf-8") as lf:
                json.dump(init_log, lf, ensure_ascii=False, indent=4)
            print(f"  [SUCCESS] Recorded execution run to 00_initialize.json")
        except Exception as e:
            print(f"  [FAILED] Could not update script 00 log: {e}")

    # -------------------------------------------------------------------------
    # PRINT PIPELINE DASHBOARD
    # -------------------------------------------------------------------------
    tracker.print_summary()

if __name__ == "__main__":
    main()
