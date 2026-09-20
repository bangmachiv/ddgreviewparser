#!/usr/bin/env python3

import json
import os
import sys
import time
import math
import logging
from urllib.parse import urlparse
from datetime import datetime
from tavily import TavilyClient

# -----------------------------------------------------------------------------
# Configuration & Absolute Pathing for GitHub Actions
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
PUBLISHERS_FILE = os.path.join(BASE_DIR, "publishers.json")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "searches")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

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


def extract_domain(url: str) -> str:
    """Extract clean domain name without www."""
    return urlparse(url).netloc.lower().replace("www.", "")

def chunk_publishers(pubs, max_chunks=3):
    """Slices publisher list into exactly 3 chunks, or fewer if very few left."""
    if not pubs:
        return []
    if len(pubs) <= max_chunks:
        return [[p] for p in pubs]

    chunk_size = math.ceil(len(pubs) / max_chunks)
    return [pubs[i:i + chunk_size] for i in range(0, len(pubs), chunk_size)]


def main():
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("[FATAL] TAVILY_API_KEY environment variable is missing.")
        return

    client = TavilyClient(api_key=api_key)

    os.makedirs(REVIEWS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL] {PUBLISHERS_FILE} not found. Cannot proceed.")
        return

    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        all_publishers = json.load(f)

    active_publishers = [p for p in all_publishers if p.get("active", False)]
    publisher_map = {extract_domain(p["url"]): p for p in active_publishers}

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
        print(f" PIPELINE STEP 1: {movie_name} (TAVILY INTEGRATION)")
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

        # Initialize all active publishers in the dictionary if they don't exist
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

        # Filter out publishers that have already succeeded
        needs_search_pubs = []
        global_done_before = 0
        global_todo_before = 0

        for p in synced_reviews_list:
            status = p.get("search_status", "PENDING")
            if status in ["PENDING", "FAILED"]:
                # Grab the full publisher object from active_publishers to get URL/Domain info
                full_pub = next((ap for ap in active_publishers if ap["id"] == p["publisher_id"]), None)
                if full_pub:
                    needs_search_pubs.append(full_pub)
                global_todo_before += 1
            else:
                global_done_before += 1

        tracker = PipelineTracker("API Payloads Fetched", global_done_before, global_todo_before)
        print(f"[STATE] {global_done_before} publishers already handled (SUCCESS).")
        print(f"[STATE] {len(needs_search_pubs)} publishers queued for web search.\n")

        # Load existing search hits
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
            "publishers_attempted": len(needs_search_pubs),
            "publishers_succeeded": 0,
            "publishers_failed": 0,
            "publisher_details": {}
        }

        # Add previously found searches to the new file payload
        needs_search_ids = {p["id"] for p in needs_search_pubs}
        for publisher in active_publishers:
            pub_id = publisher["id"]
            if pub_id not in needs_search_ids and pub_id in existing_searches_dict:
                new_searches_data["publishers"].append(existing_searches_dict[pub_id])

        if len(needs_search_pubs) > 0:
            query = f'"{movie_name}" {movie_year} movie review'
            print(f"[QUERY] {query}")

            chunks = chunk_publishers(needs_search_pubs, max_chunks=3)
            all_raw_results = []

            # Make the 3 API calls
            for idx, chunk in enumerate(chunks, start=1):
                chunk_domains = [extract_domain(p["url"]) for p in chunk]
                print(f"  └─► [Call {idx}/{len(chunks)}] Searching {len(chunk_domains)} domains...")

                try:
                    response = client.search(
                        query=query,
                        search_depth="basic",
                        max_results=20,
                        include_domains=chunk_domains
                    )
                    chunk_results = response.get("results", [])
                    all_raw_results.extend(chunk_results)
                    print(f"      [✓] Retrieved {len(chunk_results)} results for chunk {idx}.")
                except Exception as e:
                    print(f"      [x] Error on chunk {idx}: {e}")

                if idx < len(chunks):
                    time.sleep(1)

            # Map the results to their publishers locally
            matched_buckets = {p["id"]: [] for p in needs_search_pubs}

            for item in all_raw_results:
                item_url = item.get("url", "")
                item_domain = extract_domain(item_url)

                # Check domain/subdomain
                matched_pub_id = None
                for pub_domain, pub_data in publisher_map.items():
                    if item_domain == pub_domain or item_domain.endswith("." + pub_domain):
                        matched_pub_id = pub_data["id"]
                        break

                if matched_pub_id and matched_pub_id in matched_buckets:
                    # Prevent duplicates in the bucket
                    existing_urls = [r["url"] for r in matched_buckets[matched_pub_id]]
                    if item_url not in existing_urls:
                        # Removed 'snippet' entirely to save payload size
                        matched_buckets[matched_pub_id].append({
                            "rank": len(matched_buckets[matched_pub_id]) + 1,
                            "match_type": "Tavily",
                            "title": item.get("title", ""),
                            "url": item_url
                        })

            # Process the buckets and update tracker/files
            for pub in needs_search_pubs:
                pub_id = pub["id"]
                hits = matched_buckets[pub_id]

                publisher_result = {
                    "publisher_id": pub_id,
                    "publisher_name": pub["name"],
                    "results": hits
                }

                new_searches_data["publishers"].append(publisher_result)

                for p_block in reviews_data["publishers"]:
                    if p_block["publisher_id"] == pub_id:
                        if len(hits) > 0:
                            p_block["search_status"] = "SUCCESS"
                            tracker.add_success()
                            movie_log_entry["publishers_succeeded"] += 1
                            movie_log_entry["publisher_details"][pub_id] = {
                                "status": "SUCCESS",
                                "results_found": len(hits)
                            }
                        else:
                            p_block["search_status"] = "FAILED"
                            tracker.add_failure()
                            movie_log_entry["publishers_failed"] += 1
                            movie_log_entry["publisher_details"][pub_id] = {
                                "status": "FAILED", 
                                "reason": "No Results"
                            }
                        break

            reviews_data["Last searched"] = datetime.now().astimezone().strftime("%d %m %Y %H %M")
            reviews_data["Search results"] = len(needs_search_pubs)

            os.makedirs(os.path.dirname(reviews_file_path), exist_ok=True)
            with open(reviews_file_path, "w", encoding="utf-8") as rf:
                json.dump(reviews_data, rf, ensure_ascii=False, indent=4)

            os.makedirs(os.path.dirname(searches_file_path), exist_ok=True)
            with open(searches_file_path, "w", encoding="utf-8") as sf:
                json.dump(new_searches_data, sf, ensure_ascii=False, indent=4)

            print(f"\n[SUMMARY] Executed {len(chunks)} API calls across {len(needs_search_pubs)} pending publishers.")
        else:
            print(f"\n[SUMMARY] No new searches executed.")

        # Log Writer
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
