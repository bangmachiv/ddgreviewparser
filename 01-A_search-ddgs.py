#!/usr/bin/env python3
"""
01-A_search-ddgs.py
Primary search step using DDGS (9.14.4, backend='yandex,yahoo') on GitHub Actions.
Targets publishers where review_url is PENDING/FAILED/NA, executes Specific + Generic
site-scoped queries, appends deduplicated URL/domain/path-validated links with
'is_review': 'TBD' to searches_<slug>.json without overwriting prior entries, and
updates search_status and search_count in reviews_<slug>.json.
"""

import json
import os
import time
import logging
from urllib.parse import urlparse
from datetime import datetime

try:
    from ddgs import DDGS
except Exception as import_err:
    DDGS = None
    DDGS_IMPORT_ERROR = str(import_err)
else:
    DDGS_IMPORT_ERROR = None

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
# DDGS Search Constants (Verified GHA Matrix: ddgs==9.14.4, Python 3.12)
# -----------------------------------------------------------------------------
DDGS_BACKEND = "yandex,yahoo"
DDGS_REGION = "in-en"
DDGS_SAFESEARCH = "moderate"
DDGS_MAX_RESULTS = 10
DDGS_TIMEOUT = 20
DDGS_PAGE = 1
MAX_RETRIES = 3
RETRY_DELAY = 4.0
QUERY_COOLDOWN = 2.0

# Generic non-article URL path segments to exclude
BLOCKED_PATH_SEGMENTS = {
    "tag", "tags", "topic", "topics", "search",
    "video", "videos", "watch", "shorts",
    "photo", "photos", "photogallery", "gallery", "pictures", "images",
    "author", "authors", "category", "categories", "page"
}

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

        print("\n" + "=" * 105)
        print(f" PIPELINE METRIC: {self.metric_name}")
        print("=" * 105)
        print(f"| {'Done (Bef)':^10} | {'To Be Done (Bef)':^16} | {'Processed':^9} | {'Succeeded':^9} | {'Failed':^6} | {'Done (Aft)':^10} | {'To Be Done (Aft)':^16} |")
        print("-" * 105)
        print(f"| {self.done_before:^10} | {self.to_be_done_before:^16} | {self.processed:^9} | {self.succeeded:^9} | {self.failed:^6} | {done_after:^10} | {to_be_done_after:^16} |")
        print("=" * 105 + "\n")


def extract_domain(url: str) -> str:
    if not url or not isinstance(url, str):
        return ""
    try:
        return urlparse(url.strip()).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def normalize_url(url: str) -> str:
    """Canonicalizes a URL strictly for deduplication (ignores scheme, www, trailing slash, fragment)."""
    if not url or not isinstance(url, str):
        return ""
    try:
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{netloc}{path}{query}"
    except Exception:
        return url.strip().rstrip("/")


def is_valid_article_url(url: str, target_domain: str) -> bool:
    """
    Validates a candidate result strictly by URL domain & path (never by title length).
    Rejects cross-domain links, bare homepages, and generic tag/search/video/gallery hubs.
    """
    if not url or not target_domain:
        return False
    try:
        parsed = urlparse(url.strip())
        item_domain = parsed.netloc.lower().replace("www.", "")
        if not item_domain or not (item_domain == target_domain or item_domain.endswith("." + target_domain)):
            return False

        segments = [seg.lower() for seg in parsed.path.strip("/").split("/") if seg]
        if not segments:
            return False  # Reject bare homepage

        if any(seg in BLOCKED_PATH_SEGMENTS for seg in segments):
            return False

        return True
    except Exception:
        return False


def search_with_retries(query: str, max_results: int = DDGS_MAX_RESULTS):
    """Executes search with a fresh DDGS instance per attempt. Retries empty or errored responses."""
    if DDGS is None:
        return [], f"DDGS unavailable: {DDGS_IMPORT_ERROR}"

    last_error = "No results returned after max retries."
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with DDGS(timeout=DDGS_TIMEOUT) as ddgs_client:
                raw_results = ddgs_client.text(
                    query,
                    region=DDGS_REGION,
                    safesearch=DDGS_SAFESEARCH,
                    max_results=max_results,
                    backend=DDGS_BACKEND,
                    page=DDGS_PAGE,
                )
                results = list(raw_results) if raw_results else []
                if results:
                    return results, None
                last_error = "Empty results returned (retrying for intermittent backend empty responses)."
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    return [], last_error


def main():
    os.makedirs(REVIEWS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    if DDGS is None:
        print(f"[ERROR] DDGS library could not be imported ({DDGS_IMPORT_ERROR}). Exiting smoothly so downstream steps continue.")
        return

    if not os.path.exists(PUBLISHERS_FILE):
        print(f"[FATAL] {PUBLISHERS_FILE} not found. Cannot proceed.")
        return

    try:
        with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
            all_publishers = json.load(f)
    except Exception as e:
        print(f"[FATAL] Could not parse {PUBLISHERS_FILE}: {e}")
        return

    active_publishers = [p for p in all_publishers if isinstance(p, dict) and p.get("active", False)]

    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL] {MOVIES_FILE} not found. No movies to process.")
        return

    try:
        with open(MOVIES_FILE, "r", encoding="utf-8") as f:
            movies_data = json.load(f)
    except Exception as e:
        print(f"[FATAL] Could not parse {MOVIES_FILE}: {e}")
        return

    for movie in movies_data.get("movies", []):
        movie_name = movie.get("name", "")
        movie_slug = movie.get("slug", "")
        movie_date = movie.get("date", "")
        movie_year = movie_date[:4] if movie_date else ""

        if not movie_slug or not movie_name:
            print("[WARNING] Skipping movie entry with missing name or slug.")
            continue

        print("\n" + "=" * 80)
        print(f" PIPELINE STEP 1A: {movie_name} (DDGS yandex,yahoo)")
        print("=" * 80)

        movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
        script_log_path = os.path.join(movie_logs_dir, "01-A_search-ddgs.json")
        os.makedirs(movie_logs_dir, exist_ok=True)

        reviews_file_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
        if not os.path.exists(reviews_file_path):
            print(f"[ERROR] {reviews_file_path} not found. Run 00_initialize.py first. Skipping.")
            continue

        try:
            with open(reviews_file_path, "r", encoding="utf-8") as rf:
                reviews_data = json.load(rf)
        except Exception as e:
            print(f"[ERROR] Could not read {reviews_file_path}: {e}. Skipping.")
            continue

        existing_reviews_dict = {
            p.get("publisher_id"): p
            for p in (reviews_data.get("publishers") or [])
            if isinstance(p, dict) and p.get("publisher_id")
        }

        # Execution Gate: Search only if review_url is not yet confirmed
        needs_search = set()
        global_done_before = 0
        global_todo_before = 0

        for pub in active_publishers:
            pub_id = pub.get("id")
            p_block = existing_reviews_dict.get(pub_id)
            if not p_block:
                print(f"[WARNING] Publisher '{pub_id}' missing from reviews_{movie_slug}.json. Run 00_initialize.py first.")
                continue

            ru = str(p_block.get("review_url") or "PENDING").strip()
            if ru in ["PENDING", "FAILED", "NA", ""]:
                needs_search.add(pub_id)
                global_todo_before += 1
            else:
                global_done_before += 1

        tracker = PipelineTracker("DDGS Search Payloads", global_done_before, global_todo_before)
        print(f"[STATE] {global_done_before} publishers already have a confirmed review URL.")
        print(f"[STATE] {len(needs_search)} publishers queued for DDGS search.\n")

        # Load existing searches ledger safely
        searches_file_path = os.path.join(OUTPUT_DIR, f"searches_{movie_slug}.json")
        existing_searches_dict = {}
        if os.path.exists(searches_file_path) and os.path.getsize(searches_file_path) > 0:
            try:
                with open(searches_file_path, "r", encoding="utf-8") as sf:
                    old_searches_data = json.load(sf)
                if isinstance(old_searches_data, dict):
                    for sp in (old_searches_data.get("publishers") or []):
                        if isinstance(sp, dict) and sp.get("publisher_id"):
                            existing_searches_dict[sp["publisher_id"]] = sp
            except Exception as e:
                print(f"[WARNING] Could not read existing searches_{movie_slug}.json ({e}). Proceeding with fresh ledger.")

        movie_meta = reviews_data.get("movie", {"name": movie_name, "slug": movie_slug, "date": movie_date})
        new_searches_data = {
            "movie": movie_meta,
            "publishers": []
        }

        # Seed all active publisher blocks to stay synced with 00_initialize.py
        for pub in active_publishers:
            pub_id = pub.get("id")
            pub_name = pub.get("name", pub_id)
            prior_entry = existing_searches_dict.get(pub_id)
            prior_list = prior_entry.get("results") if isinstance(prior_entry, dict) and isinstance(prior_entry.get("results"), list) else []
            cleaned_prior = []
            seen_seed = set()
            for item in prior_list:
                if not isinstance(item, dict):
                    continue
                u = str(item.get("url") or "").strip()
                nu = normalize_url(u)
                if u and nu and nu not in seen_seed:
                    seen_seed.add(nu)
                    if "is_review" not in item:
                        item["is_review"] = "TBD"
                    cleaned_prior.append(item)

            new_searches_data["publishers"].append({
                "publisher_id": pub_id,
                "publisher_name": pub_name,
                "results": cleaned_prior
            })

        search_entry_map = {sp["publisher_id"]: sp for sp in new_searches_data["publishers"]}

        movie_log_entry = {
            "publishers_attempted": len(needs_search),
            "publishers_succeeded": 0,
            "publishers_failed": 0,
            "publisher_details": {}
        }

        searches_executed_count = 0

        for publisher in active_publishers:
            pub_id = publisher.get("id")
            pub_name = publisher.get("name", pub_id)

            if pub_id not in needs_search:
                continue

            searches_executed_count += 1
            domain = extract_domain(publisher.get("url", ""))

            combined_results = search_entry_map[pub_id]["results"]
            seen_urls = {normalize_url(item.get("url", "")) for item in combined_results if normalize_url(item.get("url", ""))}
            initial_count = len(combined_results)

            if not domain:
                print(f"  └─► [SKIP] Invalid or missing domain for {pub_name}.")
                tracker.add_failure()
                movie_log_entry["publishers_failed"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": "FAILED",
                    "reason": "Invalid publisher domain",
                    "total_results": len(combined_results)
                }
                continue

            print(f"  └─► Searching {pub_name} ({domain})...")

            added_specific = 0
            added_generic = 0
            err_specific = None
            err_generic = None

            try:
                query_specific = f'"{movie_name}" {movie_year} movie review site:{domain}'.strip()
                query_generic = f'{movie_name} {movie_year} movie review site:{domain}'.strip()

                results_specific, err_specific = search_with_retries(query_specific, max_results=DDGS_MAX_RESULTS)
                time.sleep(1.5)
                results_generic, err_generic = search_with_retries(query_generic, max_results=DDGS_MAX_RESULTS)

                def add_results(results_list, match_type):
                    added = 0
                    for r in results_list:
                        if not isinstance(r, dict):
                            continue
                        url = str(r.get("href") or "").strip()
                        norm_url = normalize_url(url)
                        if not url or not norm_url or norm_url in seen_urls:
                            continue

                        # Validate strictly by URL domain & path (do not filter by title length)
                        if not is_valid_article_url(url, domain):
                            continue

                        seen_urls.add(norm_url)
                        combined_results.append({
                            "rank": len(combined_results) + 1,
                            "match_type": match_type,
                            "title": str(r.get("title") or "").strip(),
                            "url": url,
                            "snippet": str(r.get("body") or "").strip(),
                            "is_review": "TBD"
                        })
                        added += 1
                    return added

                added_specific = add_results(results_specific, "Specific")
                added_generic = add_results(results_generic, "Generic")
            except Exception as e:
                err_generic = f"Unexpected search error: {type(e).__name__}: {e}"
                print(f"      [WARNING] Exception while searching {pub_name}: {err_generic}")

            new_added_total = added_specific + added_generic
            total_combined = len(combined_results)

            if new_added_total > 0:
                print(f"      [SUCCESS] Added {added_specific} Specific + {added_generic} Generic new URLs (Total in bucket: {total_combined}).")
            elif total_combined > 0:
                print(f"      [NO NEW] 0 new valid URLs found (Retained {total_combined} existing URLs).")
            else:
                reason_detail = err_specific or err_generic or "No valid results"
                print(f"      [FAILED] 0 valid URLs found ({reason_detail}).")

            # Update only search-related fields in reviews_<slug>.json
            p_block = existing_reviews_dict[pub_id]
            p_block["search_count"] = total_combined
            if total_combined > 0:
                p_block["search_status"] = "SUCCESS"
                tracker.add_success()
                movie_log_entry["publishers_succeeded"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": "SUCCESS",
                    "prior_results": initial_count,
                    "new_specific_added": added_specific,
                    "new_generic_added": added_generic,
                    "total_results": total_combined
                }
            else:
                p_block["search_status"] = "FAILED"
                tracker.add_failure()
                movie_log_entry["publishers_failed"] += 1
                movie_log_entry["publisher_details"][pub_id] = {
                    "status": "FAILED",
                    "reason": err_specific or err_generic or "No Results",
                    "total_results": 0
                }

            time.sleep(QUERY_COOLDOWN)

        if searches_executed_count > 0:
            reviews_data["Last searched"] = datetime.now().astimezone().strftime("%d %m %Y %H %M")
            reviews_data["Search results"] = searches_executed_count

            try:
                with open(reviews_file_path, "w", encoding="utf-8") as rf:
                    json.dump(reviews_data, rf, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"[ERROR] Could not save {reviews_file_path}: {e}")

            try:
                with open(searches_file_path, "w", encoding="utf-8") as sf:
                    json.dump(new_searches_data, sf, ensure_ascii=False, indent=4)
            except Exception as e:
                print(f"[ERROR] Could not save {searches_file_path}: {e}")

            print(f"\n[SUMMARY] Executed {searches_executed_count} DDGS publisher searches.")
        else:
            print(f"\n[SUMMARY] No new DDGS searches executed.")

        # Record execution log to 01-A_search-ddgs.json
        script_log_data = {}
        if os.path.exists(script_log_path) and os.path.getsize(script_log_path) > 0:
            try:
                with open(script_log_path, "r", encoding="utf-8") as lf:
                    script_log_data = json.load(lf)
            except Exception:
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
