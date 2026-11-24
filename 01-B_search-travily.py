#!/usr/bin/env python3
"""
01-B_search-tavily.py
Augmenter search step using Tavily in chunked publisher batches.
Targets active publishers where review_url is PENDING/FAILED/NA or empty,
appends deduplicated domain- and extension-validated URLs with 'snippet' and
'is_review': 'TBD' to searches_<slug>.json without overwriting prior entries,
and updates search_status and search_count in reviews_<slug>.json.
"""

import json
import os
import time
import math
import logging
from urllib.parse import urlparse
from datetime import datetime

try:
    from tavily import TavilyClient
except Exception as import_err:
    TavilyClient = None
    TAVILY_IMPORT_ERROR = str(import_err)
else:
    TAVILY_IMPORT_ERROR = None

# -----------------------------------------------------------------------------
# Configuration & Absolute Pathing for GitHub Actions
# -----------------------------------------------------------------------------
BASE_DIR = os.getcwd()
PUBLISHERS_FILE = os.path.join(BASE_DIR, "publishers.json")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "searches")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Non-article file extensions to exclude
BLOCKED_EXTENSIONS = (
    ".webp", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".pdf", ".mp4", ".mp3"
)

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


def is_valid_url_for_domain(url: str, target_domain: str) -> bool:
    """Validates strictly by target domain/subdomain and blocked non-article file extensions."""
    if not url or not target_domain:
        return False
    try:
        parsed = urlparse(url.strip())
        item_domain = parsed.netloc.lower().replace("www.", "")
        if not item_domain or not (item_domain == target_domain or item_domain.endswith("." + target_domain)):
            return False
        if parsed.path.lower().endswith(BLOCKED_EXTENSIONS):
            return False
        return True
    except Exception:
        return False


def chunk_publishers(pubs, max_chunks=3):
    if not pubs:
        return []
    if len(pubs) <= max_chunks:
        return [[p] for p in pubs]
    chunk_size = math.ceil(len(pubs) / max_chunks)
    return [pubs[i:i + chunk_size] for i in range(0, len(pubs), chunk_size)]


def main():
    os.makedirs(REVIEWS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

    if TavilyClient is None:
        print(f"[ERROR] Tavily SDK unavailable ({TAVILY_IMPORT_ERROR}). Exiting smoothly so downstream steps continue.")
        return

    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        print("[WARNING] TAVILY_API_KEY environment variable is missing. Skipping Tavily search smoothly.")
        return

    try:
        client = TavilyClient(api_key=api_key)
    except Exception as e:
        print(f"[ERROR] Failed to initialize TavilyClient ({e}). Exiting smoothly.")
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
    publisher_map = {
        extract_domain(p.get("url", "")): p
        for p in active_publishers
        if extract_domain(p.get("url", ""))
    }

    if not os.path.exists(MOVIES_FILE):
        print(f"[FATAL] {MOVIES_FILE} not found. No movies to process.")
        return

    try:
        with open(MOVIES_FILE, "r", encoding="utf-8") as f:
            movies_data = json.load(f)
    except Exception as e:
        print(f"[FATAL] Could not parse {MOVIES_FILE}: {e}")
        return

    for movie in movies_data.get("movies") or []:
        if not isinstance(movie, dict):
            continue
        movie_name = movie.get("name", "")
        movie_slug = movie.get("slug", "")
        movie_date = movie.get("date", "")
        movie_year = movie_date[:4] if movie_date else ""

        if not movie_slug or not movie_name:
            print("[WARNING] Skipping movie entry with missing name or slug.")
            continue

        print("\n" + "=" * 80)
        print(f" PIPELINE STEP 1B: {movie_name} (TAVILY CHUNKED SEARCH)")
        print("=" * 80)

        movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{movie_slug}")
        script_log_path = os.path.join(movie_logs_dir, "01-B_search-tavily.json")
        os.makedirs(movie_logs_dir, exist_ok=True)

        reviews_file_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
        searches_file_path = os.path.join(OUTPUT_DIR, f"searches_{movie_slug}.json")

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

        needs_search_pubs = []
        global_done_before = 0
        global_todo_before = 0

        # Gate on review_url: process any publisher whose review URL is not yet confirmed
        for pub in active_publishers:
            pub_id = pub.get("id")
            p_block = existing_reviews_dict.get(pub_id)
            if not p_block:
                print(f"[WARNING] Publisher '{pub_id}' missing from reviews_{movie_slug}.json. Run 00_initialize.py first.")
                continue

            ru = str(p_block.get("review_url") or "PENDING").strip()
            if ru in ["PENDING", "FAILED", "NA", ""]:
                needs_search_pubs.append(pub)
                global_todo_before += 1
            else:
                global_done_before += 1

        tracker = PipelineTracker("Tavily Search Payloads", global_done_before, global_todo_before)
        print(f"[STATE] {global_done_before} publishers already have a confirmed review URL.")
        print(f"[STATE] {len(needs_search_pubs)} publishers queued for Tavily search.\n")

        # Load existing searches ledger safely
        existing_searches_dict = {}
        if os.path.exists(searches_file_path) and os.path.getsize(searches_file_path) > 0:
            try:
                with open(searches_file_path, "r", encoding="utf-8") as sf:
                    old_sdata = json.load(sf)
                if isinstance(old_sdata, dict):
                    for sp in (old_sdata.get("publishers") or []):
                        if isinstance(sp, dict) and sp.get("publisher_id"):
                            existing_searches_dict[sp["publisher_id"]] = sp
            except Exception as e:
                print(f"[WARNING] Could not read existing searches_{movie_slug}.json ({e}). Proceeding with fresh ledger.")

        movie_meta = reviews_data.get("movie", {"name": movie_name, "slug": movie_slug, "date": movie_date})
        new_searches_data = {
            "movie": movie_meta,
            "publishers": []
        }

        # Seed all active publisher blocks & preserve prior results + is_review flags
        for pub in active_publishers:
            pub_id = pub.get("id")
            pub_name = pub.get("name", pub_id)
            prior_entry = existing_searches_dict.get(pub_id)
            prior_list = (
                prior_entry.get("results")
                if isinstance(prior_entry, dict) and isinstance(prior_entry.get("results"), list)
                else []
            )
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
                    if "snippet" not in item:
                        item["snippet"] = ""
                    cleaned_prior.append(item)

            new_searches_data["publishers"].append({
                "publisher_id": pub_id,
                "publisher_name": pub_name,
                "results": cleaned_prior
            })

        search_entry_map = {sp["publisher_id"]: sp for sp in new_searches_data["publishers"]}

        movie_log_entry = {
            "publishers_attempted": len(needs_search_pubs),
            "publishers_succeeded": 0,
            "publishers_failed": 0,
            "chunks_executed": 0,
            "chunk_errors": [],
            "publisher_details": {}
        }

        if len(needs_search_pubs) > 0:
            query = f'"{movie_name}" {movie_year} movie review'.strip()
            valid_pubs_for_chunking = [p for p in needs_search_pubs if extract_domain(p.get("url", ""))]
            chunks = chunk_publishers(valid_pubs_for_chunking, max_chunks=3)
            all_raw_results = []

            for idx, chunk in enumerate(chunks, start=1):
                chunk_domains = [extract_domain(p["url"]) for p in chunk if extract_domain(p.get("url", ""))]
                if not chunk_domains:
                    continue
                movie_log_entry["chunks_executed"] += 1
                print(f"  └─► [Call {idx}/{len(chunks)}] Searching {len(chunk_domains)} domains...")
                try:
                    response = client.search(
                        query=query,
                        search_depth="basic",
                        max_results=20,
                        include_domains=chunk_domains
                    )
                    if isinstance(response, dict):
                        raw_items = response.get("results") or []
                        all_raw_results.extend([r for r in raw_items if isinstance(r, dict)])
                except Exception as e:
                    err_msg = f"Chunk {idx}: {type(e).__name__}: {e}"
                    movie_log_entry["chunk_errors"].append(err_msg)
                    print(f"      [x] Error on {err_msg}")
                if idx < len(chunks):
                    time.sleep(1)

            seen_by_pub = {}
            initial_count_by_pub = {}
            added_count_by_pub = {}

            for pub in needs_search_pubs:
                pub_id = pub.get("id")
                existing_list = search_entry_map[pub_id]["results"]
                initial_count_by_pub[pub_id] = len(existing_list)
                added_count_by_pub[pub_id] = 0
                seen_by_pub[pub_id] = {
                    normalize_url(r.get("url", ""))
                    for r in existing_list
                    if normalize_url(r.get("url", ""))
                }

            for item in all_raw_results:
                item_url = str(item.get("url") or "").strip()
                norm_url = normalize_url(item_url)
                if not item_url or not norm_url:
                    continue

                item_domain = extract_domain(item_url)
                if not item_domain:
                    continue

                matched_pub = None
                for pub_domain, pub_data in publisher_map.items():
                    if item_domain == pub_domain or item_domain.endswith("." + pub_domain):
                        matched_pub = pub_data
                        break

                if not matched_pub:
                    continue

                matched_pub_id = matched_pub.get("id")
                if matched_pub_id not in seen_by_pub:
                    continue

                target_domain = extract_domain(matched_pub.get("url", ""))
                if not is_valid_url_for_domain(item_url, target_domain):
                    continue

                if norm_url not in seen_by_pub[matched_pub_id]:
                    seen_by_pub[matched_pub_id].add(norm_url)
                    bucket = search_entry_map[matched_pub_id]["results"]
                    bucket.append({
                        "rank": len(bucket) + 1,
                        "match_type": "Tavily",
                        "title": str(item.get("title") or "").strip(),
                        "url": item_url,
                        "snippet": str(item.get("content") or "").strip(),
                        "is_review": "TBD"
                    })
                    added_count_by_pub[matched_pub_id] += 1

            for pub in needs_search_pubs:
                pub_id = pub.get("id")
                pub_name = pub.get("name", pub_id)
                bucket = search_entry_map[pub_id]["results"]
                total_hits = len(bucket)
                new_added = added_count_by_pub.get(pub_id, 0)
                prior_cnt = initial_count_by_pub.get(pub_id, 0)

                p_block = existing_reviews_dict.get(pub_id)
                if p_block is not None:
                    p_block["search_count"] = total_hits

                if total_hits > 0:
                    if p_block is not None:
                        p_block["search_status"] = "SUCCESS"
                    tracker.add_success()
                    movie_log_entry["publishers_succeeded"] += 1
                    movie_log_entry["publisher_details"][pub_id] = {
                        "status": "SUCCESS",
                        "prior_results": prior_cnt,
                        "new_tavily_added": new_added,
                        "total_results": total_hits
                    }
                    print(f"  └─► {pub_name}: +{new_added} new Tavily URLs (Total in bucket: {total_hits}).")
                else:
                    if p_block is not None:
                        p_block["search_status"] = "FAILED"
                    tracker.add_failure()
                    movie_log_entry["publishers_failed"] += 1
                    movie_log_entry["publisher_details"][pub_id] = {
                        "status": "FAILED",
                        "reason": "No Results",
                        "total_results": 0
                    }
                    print(f"  └─► {pub_name}: 0 valid URLs in bucket.")

            reviews_data["Last searched"] = datetime.now().astimezone().strftime("%d %m %Y %H %M")
            reviews_data["Search results"] = len(needs_search_pubs)

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
        else:
            print("[SUMMARY] No publishers queued for Tavily search.")

        # Record execution log to 01-B_search-tavily.json
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
