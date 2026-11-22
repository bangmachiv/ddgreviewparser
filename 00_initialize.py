#!/usr/bin/env python3

"""
TASK: Initialize master pipeline ledgers, base files, and directory structures for all active movies.

INPUT FILES READ:
  - publishers.json (Root)
  - data/movies/movies-live-today.json

OUTPUT FOLDERS CREATED (Per Movie):
  1. data/webpages/<slugname>/
  2. data/webcontent/<slugname>/
  3. logs/logs_<slugname>/
  4. logs/logs_<slugname>/pipeline_<slugname>/

OUTPUT FILES GENERATED/UPDATED (Per Movie):
  1. data/searches/searches_<slugname>.json (Initialized for all active publishers)
  2. data/searches/negative_searches_<slugname>.json (Initialized with publisher dict)
  3. data/output/json/summary_<slugname>.json (Initialized with movie metadata + empty publishers list)
  4. data/output/wsap/wsap_<slugname>.txt (Initialized as empty file if missing)
  5. data/reviews/reviews_<slugname>.json
  6. logs/logs_<slugname>/ai_processing_logs.json (Per-publisher AI tracking blocks)
  7. 16 Empty Script Log Files based on new nomenclature in logs/logs_<slugname>/

OUTPUT FIELDS WRITTEN (Master Skeleton injected into reviews_<slugname>.json):
  publisher_id, publisher_name, search_status, search_count, review_url,
  review_title, review_source, classified_by, webpage_download,
  webpage_content_extraction, webpage_content_adjudication, article_title,
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
WEBCONTENT_DIR = os.path.join(BASE_DIR, "data", "webcontent")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
OUTPUT_JSON_DIR = os.path.join(BASE_DIR, "data", "output", "json")
OUTPUT_WSAP_DIR = os.path.join(BASE_DIR, "data", "output", "wsap")

# New flat alphabetical nomenclature (00 -> 07)
SCRIPT_LOGS = [
    "00_initialize.json",
    "01-A_search-ddgs.json",
    "01-B_search-tavily.json",
    "02-A_identify.json",
    "02-B_identify-ai.json",
    "03_download.json",
    "04-A_content.json",
    "04-B_adjudicate.json",
    "05-A_titles.json",
    "05-B_clean.json",
    "05-C_highlight.json",
    "06-A_metadata-jsonld.json",
    "06-B_metadata-ai.json",
    "06-C_label.json",
    "07-A_wsap.json",
    "07-B_summary.json"
]

# AI Processing Log Schema & Legacy Key Migration Map
AI_LOG_FIELDS = [
    "02-B_identify-ai",
    "02-B_classify-ai",
    "04-B_adjudicate",
    "05-B_clean",
    "05-C_highlight",
    "06-B_metadata-ai",
    "06-C_label"
]

AI_KEY_MIGRATIONS = {
    "02-C_identify-ai": "02-B_identify-ai",
    "02-C_classify-ai": "02-B_classify-ai",
    "04-A-2_clean": "05-B_clean",
    "04-A-3_highlight": "05-C_highlight",
    "04-B-2_metadata-ai": "06-B_metadata-ai",
    "04-B-3_label": "06-C_label"
}

RETIRED_AI_KEYS = [
    "01-C_search-gemini"
]

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

        print("\n" + "=" * 105)
        print(f" PIPELINE METRIC: {self.metric_name}")
        print("=" * 105)
        print(f"| {'Done (Bef)':^10} | {'To Be Done (Bef)':^16} | {'Processed':^9} | {'Succeeded':^9} | {'Failed':^6} | {'Done (Aft)':^10} | {'To Be Done (Aft)':^16} |")
        print("-" * 105)
        print(f"| {self.done_before:^10} | {self.to_be_done_before:^16} | {self.processed:^9} | {self.succeeded:^9} | {self.failed:^6} | {done_after:^10} | {to_be_done_after:^16} |")
        print("=" * 105 + "\n")

# -----------------------------------------------------------------------------
# Main Execution Logic
# -----------------------------------------------------------------------------
def main():
    print("=" * 80)
    print(" PIPELINE STEP 0: INITIALIZE MASTER SKELETONS")
    print("=" * 80)

    # 1. Base Output Directories (Guarantees Write Rights)
    for folder in [REVIEWS_DIR, SEARCHES_DIR, WEBPAGES_DIR, WEBCONTENT_DIR, LOGS_DIR, OUTPUT_JSON_DIR, OUTPUT_WSAP_DIR]:
        os.makedirs(folder, exist_ok=True)
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

                movie_done = sum(1 for pub in active_publishers if pub["id"] in existing_pub_ids)
                movie_todo = len(active_publishers) - movie_done

                global_done_before += movie_done
                global_to_be_done_before += movie_todo
            except Exception:
                global_to_be_done_before += len(active_publishers)
        else:
            global_to_be_done_before += len(active_publishers)

    tracker = PipelineTracker("Blocks made in reviews file", global_done_before, global_to_be_done_before)

    # -------------------------------------------------------------------------
    # ACTION RUN: Build Files, Folders, and Skeletons
    # -------------------------------------------------------------------------
    for movie in active_movies:
        movie_name = movie.get("name") or "Unknown Movie"
        movie_slug = movie.get("slug")
        movie_date = movie.get("date") or "Unknown Date"
        movie_meta = {"name": movie_name, "slug": movie_slug, "date": movie_date}

        print(f"\n[PROCESSING MOVIE] {movie_name} ({movie_slug})")

        # A. Create Movie-Specific Folders and force Git to track them
        movie_webpages_dir = os.path.join(WEBPAGES_DIR, movie_slug)
        movie_webcontent_dir = os.path.join(WEBCONTENT_DIR, movie_slug)
        movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
        movie_pipeline_logs = os.path.join(movie_logs_dir, f"pipeline_{movie_slug}")

        try:
            os.makedirs(movie_webpages_dir, exist_ok=True)
            os.makedirs(movie_webcontent_dir, exist_ok=True)
            os.makedirs(movie_logs_dir, exist_ok=True)
            os.makedirs(movie_pipeline_logs, exist_ok=True)

            # Create .gitkeep files inside the movie folders
            for target_dir in [movie_webpages_dir, movie_webcontent_dir, movie_pipeline_logs]:
                with open(os.path.join(target_dir, ".gitkeep"), "w") as f:
                    pass

            # Create empty JSON log files based on the new nomenclature
            for script_log in SCRIPT_LOGS:
                log_path = os.path.join(movie_logs_dir, script_log)
                if not os.path.exists(log_path):
                    with open(log_path, "w", encoding="utf-8") as lf:
                        json.dump({}, lf)

            print(f"  [SUCCESS] Verified webpages dir:   {movie_webpages_dir}")
            print(f"  [SUCCESS] Verified webcontent dir: {movie_webcontent_dir}")
            print(f"  [SUCCESS] Verified logs dir & {len(SCRIPT_LOGS)} script log files.")
        except Exception as e:
            print(f"  [FAILED] Could not create folders or log files: {e}")

        # B. Initialize / Sync Searches file for ALL active publishers
        searches_path = os.path.join(SEARCHES_DIR, f"searches_{movie_slug}.json")
        searches_changed = False
        searches_data = {"movie": movie_meta, "publishers": []}

        if os.path.exists(searches_path) and os.path.getsize(searches_path) > 0:
            try:
                with open(searches_path, "r", encoding="utf-8") as sf:
                    loaded_searches = json.load(sf)
                if isinstance(loaded_searches, dict) and loaded_searches:
                    searches_data = loaded_searches
                else:
                    searches_changed = True
            except Exception as e:
                print(f"  [WARNING] Corrupted searches_{movie_slug}.json ({e}). Rebuilding skeleton...")
                searches_changed = True
        else:
            searches_changed = True

        if searches_data.get("movie") != movie_meta:
            searches_data["movie"] = movie_meta
            searches_changed = True

        existing_search_pubs = {
            p.get("publisher_id"): p
            for p in (searches_data.get("publishers") or [])
            if isinstance(p, dict) and p.get("publisher_id")
        }

        search_blocks_added = 0
        search_results_patched = 0

        for pub in active_publishers:
            pub_id = pub["id"]
            if pub_id not in existing_search_pubs:
                existing_search_pubs[pub_id] = {
                    "publisher_id": pub_id,
                    "publisher_name": pub["name"],
                    "results": []
                }
                search_blocks_added += 1
                searches_changed = True
            else:
                pub_entry = existing_search_pubs[pub_id]
                if not isinstance(pub_entry.get("results"), list):
                    pub_entry["results"] = []
                    searches_changed = True
                for res in pub_entry["results"]:
                    if isinstance(res, dict) and "is_review" not in res:
                        res["is_review"] = "TBD"
                        search_results_patched += 1
                        searches_changed = True

        updated_search_pubs = list(existing_search_pubs.values())
        updated_search_pubs.sort(key=lambda x: x["publisher_id"])
        searches_data["publishers"] = updated_search_pubs

        if searches_changed or not os.path.exists(searches_path):
            try:
                with open(searches_path, "w", encoding="utf-8") as sf:
                    json.dump(searches_data, sf, ensure_ascii=False, indent=4)
                print(f"  [SUCCESS] Synced searches_{movie_slug}.json (Added {search_blocks_added} publishers, patched {search_results_patched} URLs).")
            except Exception as e:
                print(f"  [FAILED] Could not save searches file: {e}")
        else:
            print(f"  [INFO] searches_{movie_slug}.json already synced for all {len(active_publishers)} publishers.")

        # B2. Initialize Negative Searches file if missing
        negative_searches_path = os.path.join(SEARCHES_DIR, f"negative_searches_{movie_slug}.json")
        if not os.path.exists(negative_searches_path):
            try:
                with open(negative_searches_path, "w", encoding="utf-8") as sf:
                    json.dump({"movie": {"name": movie_name, "slug": movie_slug}, "publishers": {}}, sf, indent=4)
                print(f"  [SUCCESS] Created empty negative_searches_{movie_slug}.json")
            except Exception as e:
                print(f"  [FAILED] Could not create negative searches file: {e}")

        # B3. Initialize / Sync JSON Summary Output file (data/output/json/summary_<slug>.json)
        summary_path = os.path.join(OUTPUT_JSON_DIR, f"summary_{movie_slug}.json")
        summary_skeleton = {
            "movie_name": str(movie_name).strip(),
            "release_date": str(movie_date).strip(),
            "publishers": []
        }
        try:
            should_write_summary = False
            if not os.path.exists(summary_path) or os.path.getsize(summary_path) == 0:
                should_write_summary = True
            else:
                with open(summary_path, "r", encoding="utf-8") as sf:
                    existing_summary = json.load(sf)
                if not isinstance(existing_summary, dict) or existing_summary == {}:
                    should_write_summary = True

            if should_write_summary:
                with open(summary_path, "w", encoding="utf-8") as sf:
                    json.dump(summary_skeleton, sf, indent=4, ensure_ascii=False)
                print(f"  [SUCCESS] Initialized structured summary_{movie_slug}.json")
            else:
                print(f"  [INFO] Preserved existing summary_{movie_slug}.json")
        except Exception as e:
            print(f"  [FAILED] Could not initialize summary file: {e}")

        # B4. Initialize Empty WhatsApp Output file (data/output/wsap/wsap_<slug>.txt)
        wsap_path = os.path.join(OUTPUT_WSAP_DIR, f"wsap_{movie_slug}.txt")
        try:
            if not os.path.exists(wsap_path):
                with open(wsap_path, "w", encoding="utf-8") as wf:
                    pass
                print(f"  [SUCCESS] Created empty wsap_{movie_slug}.txt")
            else:
                print(f"  [INFO] Preserved existing wsap_{movie_slug}.txt")
        except Exception as e:
            print(f"  [FAILED] Could not create wsap file: {e}")

        # C. Load or Create Reviews Master Skeleton
        reviews_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")

        if os.path.exists(reviews_path):
            try:
                with open(reviews_path, "r", encoding="utf-8") as rf:
                    reviews_data = json.load(rf)
                print(f"  [INFO] Loaded existing reviews_{movie_slug}.json")
            except Exception as e:
                print(f"  [FAILED] Corrupted reviews file ({e}). Rebuilding skeleton...")
                reviews_data = {
                    "movie": movie_meta,
                    "publishers": []
                }
        else:
            reviews_data = {
                "movie": movie_meta,
                "publishers": []
            }
            print(f"  [SUCCESS] Created new reviews base object.")

        # D. Map existing and inject missing
        existing_pubs = {p.get("publisher_id"): p for p in reviews_data.get("publishers", [])}
        blocks_to_add = 0

        # D1. Clean Legacy Fields & Sync Step 3 / Step 4 Fields
        blocks_migrated = 0
        for existing_block in existing_pubs.values():
            block_changed = False

            if "search_attempts" in existing_block:
                existing_block.pop("search_attempts", None)
                block_changed = True
            if "search_count" not in existing_block:
                existing_block["search_count"] = 0
                block_changed = True
            if "search_rank" in existing_block:
                existing_block["review_source"] = existing_block.pop("search_rank")
                block_changed = True
            if "classified_by" not in existing_block:
                existing_block["classified_by"] = "PENDING"
                block_changed = True

            classified_by = existing_block.get("classified_by", "PENDING")

            # Migrate legacy download field safely without losing existing SUCCESS/FAILED states
            legacy_download = existing_block.pop("webpage_extraction_successful", None)
            if legacy_download is not None:
                block_changed = True

            if "webpage_download" not in existing_block:
                existing_block["webpage_download"] = legacy_download if legacy_download in ["SUCCESS", "FAILED"] else "PENDING"
                block_changed = True

            # Step 4 fields default to NOT_NEEDED unless classified_by == "AI"
            if "webpage_content_extraction" not in existing_block:
                existing_block["webpage_content_extraction"] = "PENDING" if classified_by == "AI" else "NOT_NEEDED"
                block_changed = True
            elif classified_by != "AI" and existing_block["webpage_content_extraction"] == "PENDING":
                existing_block["webpage_content_extraction"] = "NOT_NEEDED"
                block_changed = True

            legacy_adj = existing_block.pop("content_adjudication", None)
            if legacy_adj is not None:
                block_changed = True

            if "webpage_content_adjudication" not in existing_block:
                if legacy_adj in ["YES", "NO"]:
                    existing_block["webpage_content_adjudication"] = legacy_adj
                else:
                    existing_block["webpage_content_adjudication"] = "PENDING" if classified_by == "AI" else "NOT_NEEDED"
                block_changed = True
            elif classified_by != "AI" and existing_block["webpage_content_adjudication"] == "PENDING":
                existing_block["webpage_content_adjudication"] = "NOT_NEEDED"
                block_changed = True

            if block_changed:
                blocks_migrated += 1

        if blocks_migrated > 0:
            print(f"  [MIGRATED] Cleaned legacy fields and synced Step 3/4 fields in {blocks_migrated} existing blocks.")

        for pub in active_publishers:
            pub_id = pub["id"]
            if pub_id not in existing_pubs:
                existing_pubs[pub_id] = {
                    "publisher_id": pub_id,
                    "publisher_name": pub["name"],
                    "search_status": "PENDING",
                    "search_count": 0,
                    "review_url": "PENDING",
                    "review_title": "PENDING",
                    "review_source": "PENDING",
                    "classified_by": "PENDING",
                    "webpage_download": "PENDING",
                    "webpage_content_extraction": "NOT_NEEDED",
                    "webpage_content_adjudication": "NOT_NEEDED",
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
        if blocks_to_add > 0 or blocks_migrated > 0:
            try:
                with open(reviews_path, "w", encoding="utf-8") as rf:
                    json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
                print(f"  [SUCCESS] Injected/Updated {blocks_to_add + blocks_migrated} publishers in reviews file.")
                if blocks_to_add > 0:
                    tracker.add_success(blocks_to_add)
                save_success = True
            except Exception as e:
                print(f"  [FAILED] Could not save reviews file: {e}")
                if blocks_to_add > 0:
                    tracker.add_failure(blocks_to_add)
        else:
            print(f"  [INFO] No missing publishers to inject for this movie.")
            save_success = True

        # G. Initialize & Migrate AI Processing Logs
        ai_logs_path = os.path.join(movie_logs_dir, "ai_processing_logs.json")
        ai_logs_data = {}

        if os.path.exists(ai_logs_path) and os.path.getsize(ai_logs_path) > 0:
            try:
                with open(ai_logs_path, "r", encoding="utf-8") as af:
                    ai_logs_data = json.load(af)
            except json.JSONDecodeError:
                pass

        ai_logs_changed = False
        for pub in active_publishers:
            pub_id = pub["id"]
            if pub_id not in ai_logs_data:
                ai_logs_data[pub_id] = {field: "PENDING" for field in AI_LOG_FIELDS}
                ai_logs_changed = True
            else:
                pub_ai_log = ai_logs_data[pub_id]

                for old_key, new_key in AI_KEY_MIGRATIONS.items():
                    if old_key in pub_ai_log:
                        old_val = pub_ai_log.pop(old_key)
                        if new_key not in pub_ai_log or pub_ai_log[new_key] == "PENDING":
                            pub_ai_log[new_key] = old_val
                        ai_logs_changed = True

                for retired_key in RETIRED_AI_KEYS:
                    if retired_key in pub_ai_log:
                        pub_ai_log.pop(retired_key, None)
                        ai_logs_changed = True

                for field in AI_LOG_FIELDS:
                    if field not in pub_ai_log:
                        pub_ai_log[field] = "PENDING"
                        ai_logs_changed = True

        if ai_logs_changed or not os.path.exists(ai_logs_path):
            try:
                with open(ai_logs_path, "w", encoding="utf-8") as af:
                    json.dump(ai_logs_data, af, indent=4, ensure_ascii=False)
                print(f"  [SUCCESS] Initialized/Migrated ai_processing_logs.json for {len(active_publishers)} publishers.")
            except Exception as e:
                print(f"  [FAILED] Could not save ai_processing_logs.json: {e}")

        # H. Self-Logging execution status to 00_initialize.json
        init_log_path = os.path.join(movie_logs_dir, "00_initialize.json")
        init_log = {}

        if os.path.exists(init_log_path) and os.path.getsize(init_log_path) > 0:
            try:
                with open(init_log_path, "r", encoding="utf-8") as lf:
                    init_log = json.load(lf)
            except json.JSONDecodeError:
                pass

        timestamp = datetime.now().astimezone().isoformat()
        init_log[timestamp] = {
            "blocks_added": blocks_to_add,
            "blocks_migrated": blocks_migrated,
            "search_blocks_added": search_blocks_added,
            "total_publishers_active": len(updated_publishers),
            "status": "SUCCESS" if save_success else "FAILED"
        }

        try:
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
