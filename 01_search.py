#!/usr/bin/env python3

"""
TASK: Execute web searches via DuckDuckGo API to find potential movie review URLs.

INPUT FILES READ:
  - publishers.json
  - data/movies/movies-live-today.json
  - data/reviews/reviews_<slugname>.json (Initialized by Script 0)
  - data/searches/searches_<slugname>.json (Initialized by Script 0)

OUTPUT FILES UPDATED:
  - data/searches/searches_<slugname>.json (Raw DDG API payload injected)
  - data/reviews/reviews_<slugname>.json (State metrics updated)
  - logs/logs_<slugname>/01_search.json (Execution logs appended)

PRE-REQUISITE:
  - Publisher block exists in reviews_<slugname>.json
PENDING CONDITION (To Be Done):
  - search_needed == "Y"
SUCCESS CONDITION:
  - search_result_count is an Integer >= 0 (API returned a payload)
FAILURE CONDITION:
  - search_result_count == "FAILED" (API timeout or network error)

METRIC PUBLISHED:
  - Search results found
"""

import json
import os
import sys
from urllib.parse import urlparse
from datetime import datetime
from duckduckgo_search import DDGS

# -----------------------------------------------------------------------------
# Configuration & Absolute Pathing
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
PUBLISHERS_FILE = os.path.join(BASE_DIR, "publishers.json")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
SEARCHES_DIR = os.path.join(BASE_DIR, "data", "searches")
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


def main():
    print("=" * 80)
    print(" PIPELINE STEP 1: SEARCH DUCKDUCKGO API")
    print("=" * 80)

    # 1. Load active publishers
    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL ERROR] {PUBLISHERS_FILE} not found.")
        sys.exit(1)
        
    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        all_publishers = json.load(f)
        
    pub_url_map = {p["id"]: p.get("url", "") for p in all_publishers if p.get("active", False)}

    # 2. Load active movies
    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL ERROR] {MOVIES_FILE} not found.")
        sys.exit(1)

    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        active_movies = json.load(f).get("movies", [])

    global_done_before = 0
    global_todo_before = 0

    # -------------------------------------------------------------------------
    # PRE-SCAN: Calculate Metrics
    # -------------------------------------------------------------------------
    for movie in active_movies:
        reviews_path = os.path.join(REVIEWS_DIR, f"reviews_{movie['slug']}.json")
        if not os.path.exists(reviews_path):
            continue
            
        with open(reviews_path, "r", encoding="utf-8") as rf:
            reviews_data = json.load(rf)
            
        for pub in reviews_data.get("publishers", []):
            count_val = pub.get("search_result_count")
            needed_val = pub.get("search_needed")
            
            if isinstance(count_val, int) and count_val >= 0:
                global_done_before += 1
                
            if needed_val == "Y":
                global_todo_before += 1

    tracker = PipelineTracker("Search results found", global_done_before, global_todo_before)

    # -------------------------------------------------------------------------
    # ACTION RUN: Execute Searches
    # -------------------------------------------------------------------------
    with DDGS() as ddgs:
        for movie in active_movies:
            movie_name = movie.get("name")
            movie_slug = movie.get("slug")
            movie_date = movie.get("date", "")
            movie_year = movie_date[:4] if movie_date and len(movie_date) >= 4 else ""

            reviews_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
            searches_path = os.path.join(SEARCHES_DIR, f"searches_{movie_slug}.json")
            movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
            script_log_path = os.path.join(movie_logs_dir, "01_search.json")

            if not os.path.exists(reviews_path) or not os.path.exists(searches_path):
                print(f"[WARNING] Skipping {movie_slug}: Run Script 0 first.")
                continue

            print(f"\n[PROCESSING MOVIE] {movie_name}")
            
            with open(reviews_path, "r", encoding="utf-8") as rf:
                reviews_data = json.load(rf)
                
            with open(searches_path, "r", encoding="utf-8") as sf:
                searches_data = json.load(sf)

            movie_publishers = reviews_data.get("publishers", [])
            needs_search = [p for p in movie_publishers if p.get("search_needed") == "Y"]
            
            if not needs_search:
                print("  [INFO] No searches needed for this movie.")
                continue

            # Initialize logging dictionary for this specific movie run
            movie_log_entry = {
                "publishers_attempted": len(needs_search),
                "publishers_succeeded": 0,
                "publishers_failed": 0,
                "total_results_found": 0,
                "publisher_details": {}
            }

            for pub_block in needs_search:
                pub_id = pub_block.get("publisher_id")
                pub_name = pub_block.get("publisher_name")
                pub_url = pub_url_map.get(pub_id)
                
                if not pub_url:
                    print(f"  [ERROR] No valid URL found in publishers.json for {pub_id}")
                    pub_block["search_result_count"] = "FAILED"
                    tracker.add_failure()
                    
                    movie_log_entry["publisher_details"][pub_id] = {
                        "status": "FAILED",
                        "reason": "No valid URL mapping found",
                        "results": 0
                    }
                    movie_log_entry["publishers_failed"] += 1
                    continue

                domain = urlparse(pub_url).netloc.replace("www.", "")
                print(f"  └─► Searching {pub_name} ({domain})...")

                publisher_search_payload = {
                    "publisher_id": pub_id,
                    "publisher_name": pub_name,
                    "results": []
                }

                total_results_found = 0
                search_failed = False
                error_msgs = []

                # --- 1. BROAD SEARCH ---
                query_broad = f'{movie_name} {movie_year} movie review site:{domain}'.strip() if movie_year else f'{movie_name} movie review site:{domain}'
                
                try:
                    results_broad = list(ddgs.text(query_broad, region="in-en", backend="html", max_results=5))
                    for rank, r in enumerate(results_broad, start=1):
                        publisher_search_payload["results"].append({
                            "rank": rank,
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                            "exact_match": False
                        })
                    total_results_found += len(results_broad)
                except Exception as e:
                    print(f"      [!] Broad search failed: {e}")
                    error_msgs.append(f"Broad: {str(e)}")
                    search_failed = True

                # --- 2. EXACT MATCH SEARCH ---
                query_exact = f'"{movie_name}" {movie_year} movie review site:{domain}'.strip() if movie_year else f'"{movie_name}" movie review site:{domain}'
                
                try:
                    results_exact = list(ddgs.text(query_exact, region="in-en", backend="html", max_results=5))
                    current_rank = len(publisher_search_payload["results"]) + 1
                    for r in results_exact:
                        publisher_search_payload["results"].append({
                            "rank": current_rank,
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                            "exact_match": True
                        })
                        current_rank += 1
                    total_results_found += len(results_exact)
                except Exception as e:
                    print(f"      [!] Exact search failed: {e}")
                    error_msgs.append(f"Exact: {str(e)}")
                    search_failed = True

                # UPDATE MATRICES AND LOGS
                if search_failed and total_results_found == 0:
                    pub_block["search_result_count"] = "FAILED"
                    tracker.add_failure()
                    
                    movie_log_entry["publisher_details"][pub_id] = {
                        "status": "FAILED",
                        "reason": " | ".join(error_msgs) or "0 results returned",
                        "results": 0
                    }
                    movie_log_entry["publishers_failed"] += 1
                else:
                    searches_data[pub_id] = publisher_search_payload
                    pub_block["search_result_count"] = total_results_found
                    # Since we successfully searched, we flip the trigger off so we don't search it again next run
                    pub_block["search_needed"] = "N"
                    tracker.add_success()
                    print(f"      [SUCCESS] {total_results_found} total results found.")
                    
                    movie_log_entry["publisher_details"][pub_id] = {
                        "status": "SUCCESS",
                        "results": total_results_found
                    }
                    movie_log_entry["publishers_succeeded"] += 1
                    movie_log_entry["total_results_found"] += total_results_found

            # SAVE MOVIE DATA
            os.makedirs(os.path.dirname(reviews_path), exist_ok=True)
            with open(reviews_path, "w", encoding="utf-8") as rf:
                json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
                
            os.makedirs(os.path.dirname(searches_path), exist_ok=True)
            with open(searches_path, "w", encoding="utf-8") as sf:
                json.dump(searches_data, sf, ensure_ascii=False, indent=4)
                
            # APPEND TO SCRIPT LOG
            try:
                if os.path.exists(script_log_path):
                    with open(script_log_path, "r", encoding="utf-8") as lf:
                        script_log_data = json.load(lf)
                else:
                    script_log_data = {}
                    
                timestamp = datetime.now().astimezone().isoformat()
                script_log_data[timestamp] = movie_log_entry
                
                os.makedirs(os.path.dirname(script_log_path), exist_ok=True)
                with open(script_log_path, "w", encoding="utf-8") as lf:
                    json.dump(script_log_data, lf, ensure_ascii=False, indent=4)
                print(f"  [SUCCESS] Execution log saved to 01_search.json")
            except Exception as e:
                print(f"  [FAILED] Could not update script 01 log: {e}")

    # -------------------------------------------------------------------------
    # PRINT PIPELINE DASHBOARD
    # -------------------------------------------------------------------------
    tracker.print_summary()

if __name__ == "__main__":
    main()
