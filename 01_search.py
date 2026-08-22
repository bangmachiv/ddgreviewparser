#!/usr/bin/env python3

import json
import os
import sys
import time
import logging
from urllib.parse import urlparse
from datetime import datetime
from ddgs import DDGS

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
# DDGS Search Constants
# -----------------------------------------------------------------------------
MAX_RETRIES = 3
RETRY_DELAY = 2
QUERY_COOLDOWN = 1.5

logging.basicConfig(level=logging.ERROR, format="%(asctime)s [%(levelname)s] %(message)s")

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


def search_with_retries(query: str, max_results: int = 5):
    """Executes search with a fresh DDGS instance per attempt to prevent connection poisoning."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with DDGS(timeout=30) as ddgs_client:
                results = list(
                    ddgs_client.text(
                        query,
                        region="in-en",
                        max_results=max_results,
                    )
                )
                if results:
                    return results, None
        except Exception:
            pass 
            
        if attempt < MAX_RETRIES:
            time.sleep(attempt * RETRY_DELAY)

    return [], "No results returned after max retries."


def main():
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

    for movie in movies_data.get("movies", []):
        movie_name = movie.get("name")
        movie_slug = movie.get("slug")
        movie_date = movie.get("date", "")
        movie_year = movie_date[:4] if movie_date else ""

        print("\n" + "=" * 80)
        print(f" PIPELINE STEP 1: {movie_name}")
        print("=" * 80)

        movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
        script_log_path = os.path.join(movie_logs_dir, "01_search.json")
        os.makedirs(movie_logs_dir, exist_ok=True)

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
            
            # Aggressively retry anything that is PENDING or FAILED
            if status in ["PENDING", "FAILED"]:
                needs_search.add(p["publisher_id"])
                global_todo_before += 1
            else:
                global_done_before += 1

        tracker = PipelineTracker("API Payloads Fetched", global_done_before, global_todo_before)
        print(f"[STATE] {global_done_before} publishers already handled (SUCCESS).")
        print(f"[STATE] {len(needs_search)} publishers queued for web search.\n")

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

        movie_log_entry = {
            "publishers_attempted": len(needs_search),
            "publishers_succeeded": 0,
            "publishers_failed": 0,
            "publisher_details": {}
        }

        searches_executed_count = 0  

        for publisher in active_publishers:
            pub_id = publisher["id"]

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

            # Year is included as a loose keyword, outside the quoted title
            query_specific = f'"{movie_name}" movie review {movie_year} site:{domain}'
            query_generic = f'{movie_name} movie review {movie_year} site:{domain}'

            # Both query types run back to back, independently
            results_specific, err_specific = search_with_retries(query_specific, max_results=5)
            time.sleep(1)
            results_generic, err_generic = search_with_retries(query_generic, max_results=5)

            total_results_found = len(results_specific) + len(results_generic)

            for rank, r in enumerate(results_specific, start=1):
                publisher_result["results"].append({
                    "rank": rank,
                    "match_type": "Specific",
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })

            for rank, r in enumerate(results_generic, start=1):
                publisher_result["results"].append({
                    "rank": rank,
                    "match_type": "Generic",
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })

            if total_results_found > 0:
                print(f"      [SUCCESS] Found {len(results_specific)} URLs via Specific query, {len(results_generic)} via Generic query.")
            else:
                print(f"      [FAILED] 0 URLs returned across both queries.")

            new_searches_data["publishers"].append(publisher_result)

            for p_block in reviews_data["publishers"]:
                if p_block["publisher_id"] == pub_id:
                    if total_results_found > 0:
                        p_block["search_status"] = "SUCCESS"
                        tracker.add_success()
                        movie_log_entry["publishers_succeeded"] += 1
                        movie_log_entry["publisher_details"][pub_id] = {
                            "status": "SUCCESS",
                            "specific_results": len(results_specific),
                            "generic_results": len(results_generic)
                        }
                    else:
                        p_block["search_status"] = "FAILED"
                        tracker.add_failure()
                        movie_log_entry["publishers_failed"] += 1
                        movie_log_entry["publisher_details"][pub_id] = {"status": "FAILED", "reason": "No Results"}
                    break

            time.sleep(QUERY_COOLDOWN)

        if searches_executed_count > 0:
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

        # Fixed Logging Block: Completely immune to empty JSON file crashes
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
