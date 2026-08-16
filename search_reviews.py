#!/usr/bin/env python3

import json
import os
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

def main():
    # -----------------------------
    # 1. Setup & Load Core Data
    # -----------------------------
    # Forcefully create the directories at the repo root
    os.makedirs(REVIEWS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL] {PUBLISHERS_FILE} not found. Cannot proceed.")
        return
        
    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        all_publishers = json.load(f)
    
    # Filter for active publishers only
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

            # ---------------------------------------------------------
            # PHASE A: SYNC THE 'REVIEWS_' SKELETON
            # ---------------------------------------------------------
            reviews_file_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
            
            # Load existing reviews or create a fresh skeleton
            if os.path.exists(reviews_file_path):
                with open(reviews_file_path, "r", encoding="utf-8") as rf:
                    reviews_data = json.load(rf)
            else:
                print(f"[INIT] Creating fresh review skeleton for {movie_slug}")
                reviews_data = {
                    "movie": {
                        "name": movie_name,
                        "slug": movie_slug,
                        "date": movie_date
                    },
                    "Last searched": "", 
                    "Search results": 0,
                    "publishers": []
                }

            # Map existing publishers to easily detect who is missing
            existing_reviews_dict = {
                p.get("publisher_id"): p for p in reviews_data.get("publishers", [])
            }

            # Inject any active publishers that are missing from the review file
            for pub in active_publishers:
                pub_id = pub["id"]
                if pub_id not in existing_reviews_dict:
                    existing_reviews_dict[pub_id] = {
                        "publisher_id": pub_id,
                        "publisher_name": pub["name"],
                        "review_url": "NA",
                        "review_title": "NA",
                        "search_rank": "NA",
                        "article_title": None
                    }

            # Rebuild the list ensuring it perfectly matches the master publishers.json order
            synced_reviews_list = []
            for pub in active_publishers:
                synced_reviews_list.append(existing_reviews_dict[pub["id"]])
            
            reviews_data["publishers"] = synced_reviews_list

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
