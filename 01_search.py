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

    # 1. Load active publishers (Needed to get the target URL domains)
    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL ERROR] {PUBLISHERS_FILE} not found.")
        sys.exit(1)
        
    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        all_publishers = json.load(f)
        
    # Create a quick lookup dictionary for publisher URLs based on ID
    pub_url_map = {p["id"]: p.get("url", "") for p in all_publishers if p.get("active", False)}

    # 2. Load active movies
    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL ERROR] {MOVIES_FILE} not found.")
        sys.exit(1)

    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        active_movies = json.load(f).get("movies", [])

    # Initialize global tracking
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
            
            # Done Before: count is an integer >= 0
            if isinstance(count_val, int) and count_val >= 0:
                global_done_before += 1
                
            # To Be Done Before: search_needed == "Y"
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

            if not os.path.exists(reviews_path) or not os.path.exists(searches_path):
                print(f"[WARNING] Skipping {movie_slug}: Run Script 0 first.")
                continue

            print(f"\n[PROCESSING MOVIE] {movie_name}")
            
            with open(reviews_path, "r", encoding="utf-8") as rf:
                reviews_data = json.load(rf)
                
            with open(searches_path, "r", encoding="utf-8") as sf:
                searches_data = json.load(sf)

            movie_publishers = reviews_data.get("publishers", [])
            
            # Identify publishers needing search
            needs_search = [p for p in movie_publishers if p.get("search_needed") == "Y"]
            
            if not needs_search:
                print("  [INFO] No searches needed for this movie.")
                continue

            # Process the backlog
            for pub_block in needs_search:
                pub_id = pub_block.get("publisher_id")
                pub_name = pub_block.get("publisher_name")
                pub_url = pub_url_map.get(pub_id)
                
                if not pub_url:
                    print(f"  [ERROR] No valid URL found in publishers.json for {pub_id}")
                    pub_block["search_result_count"] = "FAILED"
                    tracker.add_failure()
                    continue

                domain = urlparse(pub_url).netloc.replace("www.", "")
                print(f"  └─► Searching {pub_name} ({domain})...")

                # Setup payload for searches_.json
                publisher_search_payload = {
                    "publisher_id": pub_id,
                    "publisher_name": pub_name,
                    "results": []
                }

                total_results_found = 0
                search_failed = False

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
                    search_failed = True

                # UPDATE MATRICES
                if search_failed and total_results_found == 0:
                    pub_block["search_result_count"] = "FAILED"
                    tracker.add_failure()
                else:
                    # Save results to the searches dict
                    searches_data[pub_id] = publisher_search_payload
                    # Update master ledger block
                    pub_block["search_result_count"] = total_results_found
                    tracker.add_success()
                    print(f"      [SUCCESS] {total_results_found} total results found.")

            # SAVE MOVIE DATA
            with open(reviews_path, "w", encoding="utf-8") as rf:
                json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
                
            with open(searches_path, "w", encoding="utf-8") as sf:
                json.dump(searches_data, sf, ensure_ascii=False, indent=4)

    # -------------------------------------------------------------------------
    # PRINT PIPELINE DASHBOARD
    # -------------------------------------------------------------------------
    tracker.print_summary()

if __name__ == "__main__":
    main()
            # SAVE #1: Lock in the skeleton before searching.
            os.makedirs(os.path.dirname(reviews_file_path), exist_ok=True)
            try:
                with open(reviews_file_path, "w", encoding="utf-8") as rf:
                    json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
                print(f"[SYNC] reviews_{movie_slug}.json securely synced with {len(active_publishers)} publishers.")
            except Exception as e:
                print(f"[FATAL ERROR] GitHub Actions failed to create file '{reviews_file_path}'. Reason: {e}")
                continue # Skip to next movie if file creation hard-fails

            # ---------------------------------------------------------
            # PHASE B: DETERMINE WHO NEEDS SEARCHING
            # ---------------------------------------------------------
            needs_search = set()
            for p in synced_reviews_list:
                r_url = str(p.get("review_url", "")).strip()
                # If the URL is empty or strictly "NA", it goes on the search list
                if r_url == "" or r_url.upper() == "NA":
                    needs_search.add(p["publisher_id"])
            
            print(f"[STATE] {len(active_publishers) - len(needs_search)} publishers already have URLs.")
            print(f"[STATE] {len(needs_search)} publishers queued for web search.")

            # ---------------------------------------------------------
            # PHASE C: LOAD EXISTING SEARCH HISTORY
            # ---------------------------------------------------------
            searches_file_path = os.path.join(OUTPUT_DIR, f"searches_{movie_slug}.json")
            existing_searches_dict = {}
            if os.path.exists(searches_file_path):
                with open(searches_file_path, "r", encoding="utf-8") as sf:
                    try:
                        old_searches_data = json.load(sf)
                        for sp in old_searches_data.get("publishers", []):
                            existing_searches_dict[sp.get("publisher_id")] = sp
                    except Exception:
                        pass

            new_searches_data = {
                "movie": reviews_data["movie"],
                "publishers": []
            }

            # ---------------------------------------------------------
            # PHASE D: EXECUTE REQUIRED SEARCHES
            # ---------------------------------------------------------
            searches_executed_count = 0  

            for publisher in active_publishers:
                pub_id = publisher["id"]
                
                # SKIP RULE: If we don't need a search, carry over old data (if any) and skip
                if pub_id not in needs_search:
                    if pub_id in existing_searches_dict:
                        new_searches_data["publishers"].append(existing_searches_dict[pub_id])
                    continue

                # EXECUTE RULE: Publisher is missing URL, begin search
                searches_executed_count += 1
                domain = urlparse(publisher["url"]).netloc.replace("www.", "")
                
                print(f"  └─► Searching {publisher['name']} (Broad & Exact)...")
                
                publisher_result = {
                    "publisher_id": pub_id,
                    "publisher_name": publisher["name"],
                    "publisher_url": publisher["url"],
                    "results": []
                }

                # --- 1. BROAD SEARCH ---
                query_broad = f'{movie_name} {movie_year} movie review site:{domain}'.strip() if movie_year else f'{movie_name} movie review site:{domain}'
                publisher_result["query_broad"] = query_broad
                
                try:
                    results_broad = list(ddgs.text(query_broad, region="in-en", backend="html", max_results=5))
                    for rank, r in enumerate(results_broad, start=1):
                        publisher_result["results"].append({
                            "rank": rank,
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                            "exact_match": False
                        })
                except Exception as e:
                    publisher_result["error_broad"] = str(e)

                # --- 2. EXACT MATCH SEARCH ---
                query_exact = f'"{movie_name}" {movie_year} movie review site:{domain}'.strip() if movie_year else f'"{movie_name}" movie review site:{domain}'
                publisher_result["query_exact"] = query_exact
                
                try:
                    results_exact = list(ddgs.text(query_exact, region="in-en", backend="html", max_results=5))
                    if not results_exact:
                        print(f"      [!] 0 exact match results returned.")
                    
                    current_rank = len(publisher_result["results"]) + 1
                    for r in results_exact:
                        publisher_result["results"].append({
                            "rank": current_rank,
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                            "exact_match": True
                        })
                        current_rank += 1
                except Exception as e:
                    publisher_result["error_exact"] = str(e)

                new_searches_data["publishers"].append(publisher_result)

            # ---------------------------------------------------------
            # PHASE E: UPDATE SOURCE OF TRUTH & SAVE
            # ---------------------------------------------------------
            # 1. Update the Master Reviews File with the flat execution fields
            reviews_data["Last searched"] = datetime.now().astimezone().strftime("%d %m %Y %H %M")
            reviews_data["Search results"] = searches_executed_count
            
            os.makedirs(os.path.dirname(reviews_file_path), exist_ok=True)
            with open(reviews_file_path, "w", encoding="utf-8") as rf:
                json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
            
            # 2. Dump the raw search results
            os.makedirs(os.path.dirname(searches_file_path), exist_ok=True)
            with open(searches_file_path, "w", encoding="utf-8") as f:
                json.dump(new_searches_data, f, ensure_ascii=False, indent=4)
            
            print(f"\n[SUMMARY] Executed {searches_executed_count} new searches.")
            print(f"[SAVED] Metadata updated in {reviews_file_path}")
            print(f"[SAVED] Search results committed to {searches_file_path}")

if __name__ == "__main__":
    main()
