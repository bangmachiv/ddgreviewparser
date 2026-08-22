#!/usr/bin/env python3

import json
import os
import sys
import time
from urllib.parse import urlparse
from datetime import datetime
from duckduckgo_search import DDGS

# -----------------------------------------------------------------------------
# Configuration & Absolute Pathing for GitHub Actions
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
PUBLISHERS_FILE = os.path.join(BASE_DIR, "publishers.json")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "searches")
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
    # -----------------------------
    # 1. Setup & Load Core Data
    # -----------------------------
    os.makedirs(REVIEWS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL] {PUBLISHERS_FILE} not found. Cannot proceed.")
        return
        
    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        all_publishers = json.load(f)
    
    active_publishers = [p for p in all_publishers if p.get("active", False)]

    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL] {MOVIES_FILE} not found. No movies to process.")
        return

    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        movies_data = json.load(f)

    with DDGS() as ddgs:
        for movie in movies_data.get("movies", []):
            movie_name = movie.get("name")
            movie_slug = movie.get("slug")
            movie_date = movie.get("date", "")
            movie_year = movie_date[:4] if movie_date and len(movie_date) >= 4 else ""

            print("\n" + "=" * 80)
            print(f" PIPELINE STEP 1: {movie_name}")
            print("=" * 80)

            movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
            script_log_path = os.path.join(movie_logs_dir, "01_search.json")
            os.makedirs(movie_logs_dir, exist_ok=True)

            # ---------------------------------------------------------
            # PHASE A: SYNC THE 'REVIEWS_' SKELETON (Restored your logic)
            # ---------------------------------------------------------
            reviews_file_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
            
            if os.path.exists(reviews_file_path):
                with open(reviews_file_path, "r", encoding="utf-8") as rf:
                    reviews_data = json.load(rf)
            else:
                print(f"[INIT] Creating fresh review skeleton for {movie_slug}")
                reviews_data = {
                    "movie": {"name": movie_name, "slug": movie_slug, "date": movie_date},
                    "Last searched": "", 
                    "Search results": 0,
                    "publishers": []
                }

            existing_reviews_dict = {p.get("publisher_id"): p for p in reviews_data.get("publishers", [])}

            for pub in active_publishers:
                pub_id = pub["id"]
                if pub_id not in existing_reviews_dict:
                    existing_reviews_dict[pub_id] = {
                        "publisher_id": pub_id,
                        "publisher_name": pub["name"],
                        "search_status": "PENDING",
                        "search_attempts": 0,
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

            synced_reviews_list = []
            for pub in active_publishers:
                synced_reviews_list.append(existing_reviews_dict[pub["id"]])
            
            reviews_data["publishers"] = synced_reviews_list

            try:
                os.makedirs(os.path.dirname(reviews_file_path), exist_ok=True)
                with open(reviews_file_path, "w", encoding="utf-8") as rf:
                    json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
                print(f"[SYNC] reviews_{movie_slug}.json securely synced.")
            except Exception as e:
                print(f"[FATAL ERROR] Failed to sync reviews file: {e}")
                continue 

            # ---------------------------------------------------------
            # PHASE B: DETERMINE WHO NEEDS SEARCHING
            # ---------------------------------------------------------
            needs_search = set()
            global_done_before = 0
            global_todo_before = 0

            for p in synced_reviews_list:
                status = p.get("search_status", "PENDING")
                if status == "PENDING":
                    needs_search.add(p["publisher_id"])
                    global_todo_before += 1
                else:
                    global_done_before += 1
            
            tracker = PipelineTracker("API Payloads Fetched", global_done_before, global_todo_before)
            print(f"[STATE] {global_done_before} publishers already handled.")
            print(f"[STATE] {len(needs_search)} publishers queued for web search.")

            # ---------------------------------------------------------
            # PHASE C: LOAD EXISTING SEARCH HISTORY (Restored your array structure)
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
                "publishers": [] # Back to your original list structure
            }

            movie_log_entry = {
                "publishers_attempted": len(needs_search),
                "publishers_succeeded": 0,
                "publishers_failed": 0,
                "publisher_details": {}
            }

            # ---------------------------------------------------------
            # PHASE D: EXECUTE REQUIRED SEARCHES
            # ---------------------------------------------------------
            searches_executed_count = 0  

            for publisher in active_publishers:
                pub_id = publisher["id"]
                
                # SKIP RULE: Carry over old data and skip
                if pub_id not in needs_search:
                    if pub_id in existing_searches_dict:
                        new_searches_data["publishers"].append(existing_searches_dict[pub_id])
                    continue

                searches_executed_count += 1
                domain = urlparse(publisher["url"]).netloc.replace("www.", "")
                
                print(f"  └─► Searching {publisher['name']} ({domain})...")
                
                publisher_result = {
                    "publisher_id": pub_id,
                    "publisher_name": publisher["name"],
                    "results": []
                }

                total_results_found = 0
                error_msgs = []

                # --- 1. BROAD SEARCH ---
                query_broad = f'{movie_name} {movie_year} movie review site:{domain}'.strip() if movie_year else f'{movie_name} movie review site:{domain}'
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
                    total_results_found += len(results_broad)
                except Exception as e:
                    error_msgs.append("Broad API Error")

                # ANTI-BOT SLEEP (Critical fix to prevent empty [] payloads)
                time.sleep(2)

                # --- 2. EXACT MATCH SEARCH ---
                query_exact = f'"{movie_name}" {movie_year} movie review site:{domain}'.strip() if movie_year else f'"{movie_name}" movie review site:{domain}'
                try:
                    results_exact = list(ddgs.text(query_exact, region="in-en", backend="html", max_results=5))
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
                    total_results_found += len(results_exact)
                except Exception as e:
                    error_msgs.append("Exact API Error")

                new_searches_data["publishers"].append(publisher_result)

                # Find the matching block in the synced reviews list to update status
                for p_block in reviews_data["publishers"]:
                    if p_block["publisher_id"] == pub_id:
                        if total_results_found > 0:
                            p_block["search_status"] = "SUCCESS"
                            tracker.add_success()
                            movie_log_entry["publishers_succeeded"] += 1
                            movie_log_entry["publisher_details"][pub_id] = {"status": "SUCCESS"}
                            print(f"      [SUCCESS] Found {total_results_found} URLs.")
                        else:
                            p_block["search_status"] = "FAILED"
                            tracker.add_failure()
                            movie_log_entry["publishers_failed"] += 1
                            movie_log_entry["publisher_details"][pub_id] = {"status": "FAILED", "reason": "No URLs returned (Possible Block)"}
                            print(f"      [FAILED] 0 URLs returned.")
                        break

                # SECOND ANTI-BOT SLEEP
                time.sleep(1)

            # ---------------------------------------------------------
            # PHASE E: UPDATE SOURCE OF TRUTH & SAVE
            # ---------------------------------------------------------
            if searches_executed_count > 0:
                # Update your original root metadata fields
                reviews_data["Last searched"] = datetime.now().astimezone().strftime("%d %m %Y %H %M")
                reviews_data["Search results"] = searches_executed_count
                
                os.makedirs(os.path.dirname(reviews_file_path), exist_ok=True)
                with open(reviews_file_path, "w", encoding="utf-8") as rf:
                    json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
                
                os.makedirs(os.path.dirname(searches_file_path), exist_ok=True)
                with open(searches_file_path, "w", encoding="utf-8") as sf:
                    json.dump(new_searches_data, sf, ensure_ascii=False, indent=4)
                
                print(f"\n[SUMMARY] Executed {searches_executed_count} new searches.")
            else:
                print(f"\n[SUMMARY] No new searches executed.")

            # Append to your individual script log
            try:
                if os.path.exists(script_log_path):
                    with open(script_log_path, "r", encoding="utf-8") as lf:
                        script_log_data = json.load(lf)
                else:
                    script_log_data = {}
                    
                timestamp = datetime.now().astimezone().isoformat()
                script_log_data[timestamp] = movie_log_entry
                
                with open(script_log_path, "w", encoding="utf-8") as lf:
                    json.dump(script_log_data, lf, ensure_ascii=False, indent=4)
            except Exception as e:
                pass

            tracker.print_summary()

if __name__ == "__main__":
    main()
