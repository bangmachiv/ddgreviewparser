#!/usr/bin/env python3

import json
import os

# -----------------------------------------------------------------------------
# Configuration & Absolute Pathing for GitHub Actions
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
PUBLISHERS_FILE = os.path.join(BASE_DIR, "publishers.json")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")

def main():
    print("=" * 80)
    print(" PIPELINE STEP 0: INITIALIZE MASTER SKELETONS")
    print("=" * 80)

    # 1. Ensure output directory exists
    os.makedirs(REVIEWS_DIR, exist_ok=True)

    # 2. Load active publishers
    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL] {PUBLISHERS_FILE} not found. Cannot proceed.")
        return
        
    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        all_publishers = json.load(f)
    
    active_publishers = [p for p in all_publishers if p.get("active", False)]

    # 3. Load active movies
    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL] {MOVIES_FILE} not found. No movies to process.")
        return

    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        movies_data = json.load(f)

    # 4. Process each movie
    for movie in movies_data.get("movies", []):
        movie_name = movie.get("name")
        movie_slug = movie.get("slug")
        movie_date = movie.get("date", "")
        
        print(f"\n[CHECKING] {movie_name} ({movie_slug})")
        
        reviews_file_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
        
        # Phase A: Load existing file or create base structure
        if os.path.exists(reviews_file_path):
            try:
                with open(reviews_file_path, "r", encoding="utf-8") as rf:
                    reviews_data = json.load(rf)
            except Exception as e:
                print(f"  [ERROR] Failed to read {reviews_file_path}: {e}")
                continue
        else:
            print(f"  [INIT] Creating new reviews file...")
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

        # Phase B: Map existing publishers to detect who is missing
        existing_pubs = {p.get("publisher_id"): p for p in reviews_data.get("publishers", [])}
        
        # Phase C: Inject missing publishers with exact Master Skeleton
        added_count = 0
        for pub in active_publishers:
            pub_id = pub["id"]
            if pub_id not in existing_pubs:
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
                added_count += 1
                
        # Phase D: Sort alphabetically by publisher_id
        updated_publishers = list(existing_pubs.values())
        updated_publishers.sort(key=lambda x: x["publisher_id"])
        
        reviews_data["publishers"] = updated_publishers
        
        # Phase E: Save file
        try:
            with open(reviews_file_path, "w", encoding="utf-8") as rf:
                json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
            print(f"  [SUCCESS] File synced. Total Publishers: {len(updated_publishers)} (Added: {added_count})")
        except Exception as e:
            print(f"  [FATAL ERROR] GitHub Actions failed to create file '{reviews_file_path}'. Reason: {e}")

if __name__ == "__main__":
    main()
