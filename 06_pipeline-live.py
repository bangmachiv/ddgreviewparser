#!/usr/bin/env python3
"""
06_pipeline-live.py
Collects metrics from logs and reviews data to produce:
  1. A tabular per-script execution table split across two lines to prevent wrapping.
  2. The Final News Status count breakdown.
Outputs to console and saves to logs/logs_<slug>/pipeline_<slug>/run_<timestamp>.txt.
"""

import json
import os
import glob
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")

# Sequence of pipeline scripts that log metrics
PIPELINE_STAGES = [
    ("01_search", "01_search.json"),
    ("02_identify", "02_identify.json"),
    ("02-C_identify-ai", "02-C_identify-ai.json"),
    ("03_download", "03_download.json"),
    ("04-A-1_titles", "04-A-1_titles.json"),
    ("04-A-2_clean", "04-A-2_clean.json"),
    ("04-A-3_highlight", "04-A-3_highlight.json"),
    ("04-B-1_metadata-jsonld", "04-B-1_metadata-jsonld.json"),
    ("04-B-2_metadata-ai", "04-B-2_metadata-ai.json"),
    ("04-B-3_label", "04-B-3_label.json"),
    ("05-A_wsap", "05-A_output-wsap.json")
]

VALID_CATEGORIES = ["GOOD", "NEUTRAL", "BAD", "POSITIVE", "MIXED", "NEGATIVE"]

def is_valid(val):
    if val is None:
        return False
    clean = str(val).strip().upper()
    return clean not in ["", "PENDING", "FAILED", "NA", "NOT_NEEDED", "NULL"]

def is_valid_number(val):
    if not is_valid(val):
        return False
    try:
        float(val)
        return True
    except ValueError:
        return False

def get_live_movie_slugs():
    slugs = []
    if os.path.exists(MOVIES_FILE):
        with open(MOVIES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            items = data if isinstance(data, list) else data.get("movies", [])
            for item in items:
                if isinstance(item, dict) and "slug" in item:
                    slugs.append(item["slug"])
    else:
        for p in glob.glob(os.path.join(REVIEWS_DIR, "reviews_*.json")):
            base = os.path.basename(p)
            slugs.append(base.replace("reviews_", "").replace(".json", ""))
    return list(set(slugs))

def extract_latest_log_metrics(log_path, total_pubs=0, rdata=None, stage_name=""):
    run = {}
    if os.path.exists(log_path) and os.path.getsize(log_path) > 0:
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data:
                latest_ts = sorted(data.keys())[-1]
                run = data[latest_ts]
        except Exception:
            pass

    # 1. 05-A Custom Parsing
    if "total_reviews_formatted" in run:
        success = run.get("total_reviews_formatted", 0)
        processed = total_pubs
        had_to_do = total_pubs
        failure = processed - success
        return had_to_do, processed, failure, success

    # 2. Greedy Alias Parsing for 01-04
    def get_first(keys):
        for k in keys:
            if k in run: return run[k]
        return 0

    had_to_do = get_first(["earlier_pending", "pending", "targets", "target_publishers", "publishers_evaluated"])
    processed = get_first(["processed", "attempted", "searches", "searches_performed", "publishers_evaluated"])
    success = get_first(["success", "succeeded", "found", "results", "matches_found"])
    failure = get_first(["failure", "failed", "errors", "no_matches_found"])

    # 3. 01_search JSON Overwrite (Fixes the 00|00|00|00 logic issue)
    if "01_search" in stage_name and processed == 0 and success == 0 and rdata:
        search_results = rdata.get("Search results")
        if search_results is not None:
            had_to_do = 1
            processed = 1
            success = search_results
            failure = 0

    if not run and "01_search" not in stage_name:
        return None

    return had_to_do, processed, failure, success

def pad_num(val):
    """Returns a zero-padded string for integers, or passes through raw strings (e.g., '--')."""
    return f"{val:02d}" if isinstance(val, int) else str(val)

def process_slug(slug):
    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{slug}")
    review_path = os.path.join(REVIEWS_DIR, f"reviews_{slug}.json")

    total_pubs = 0
    rdata = {}
    if os.path.exists(review_path):
        with open(review_path, "r", encoding="utf-8") as f:
            rdata = json.load(f)
        total_pubs = len(rdata.get("publishers", []))

    # --- 1. Tabular Execution Data ---
    stage_rows = []
    for idx, (stage_name, log_filename) in enumerate(PIPELINE_STAGES, start=1):
        log_file = os.path.join(movie_logs_dir, log_filename)
        metrics = extract_latest_log_metrics(log_file, total_pubs, rdata, stage_name)

        stage_rows.append(f"{idx:02d}. {stage_name}")

        if metrics:
            had, proc, fail, succ = metrics
            # Stripped out the >7 and >9 padding, relying only on pad_num and spaces
            stage_rows.append(f"{pad_num(had)} | {pad_num(proc)} | {pad_num(fail)} | {pad_num(succ)}")
        else:
            stage_rows.append(f"-- | -- | -- | --")

    # --- 2. Final News Status Counts ---
    status_counts = {
        "Urls identified": 0,
        "Html Downloaded": 0,
        "Extracted titles": 0,
        "Cleaned titles": 0,
        "Highlight titles": 0,
        "Jsonld rated": 0,
        "Ai rated": 0,
        "Ai labeled": 0,
    }

    if rdata:
        for pub in rdata.get("publishers", []):
            if is_valid(pub.get("review_url")):
                status_counts["Urls identified"] += 1

            dl_ok = pub.get("webpage_extraction_successful")
            if dl_ok is True or str(dl_ok).strip().upper() in ["SUCCESS", "Y", "YES", "TRUE"]:
                status_counts["Html Downloaded"] += 1

            if is_valid(pub.get("article_title")):
                status_counts["Extracted titles"] += 1

            if is_valid(pub.get("clean_title")):
                status_counts["Cleaned titles"] += 1

            ht = pub.get("highlighted_title", pub.get("clean_highlighted_title"))
            if is_valid(ht):
                status_counts["Highlight titles"] += 1

            if is_valid_number(pub.get("jsonld_star_rating")):
                status_counts["Jsonld rated"] += 1

            if is_valid_number(pub.get("ai_star_rating")):
                status_counts["Ai rated"] += 1

            ai_cat = str(pub.get("ai_sentiment_category", "")).strip().upper()
            if ai_cat in VALID_CATEGORIES:
                status_counts["Ai labeled"] += 1

    # --- 3. Build Formatted Output ---
    output_lines = []
    output_lines.append("=" * 45)
    output_lines.append(f" SUMMARY: {slug}")
    output_lines.append("=" * 45)
    output_lines.append("Script No & Name")
    # Abbreviated headers to prevent wrapping
    output_lines.append("HTD | PRO | FAI | SUC")
    output_lines.append("-" * 45)
    output_lines.extend(stage_rows)
    output_lines.append("")
    output_lines.append("=" * 45)
    output_lines.append(" FINAL NEWS STATUS")
    output_lines.append("=" * 45)
    for label, count in status_counts.items():
        output_lines.append(f"{label:<22}: {pad_num(count)}")
    output_lines.append("=" * 45)

    report = "\n".join(output_lines)
    print("\n" + report + "\n")

    # --- 4. Write run log to target directory ---
    target_dir = os.path.join(movie_logs_dir, f"pipeline_{slug}")
    os.makedirs(target_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = os.path.join(target_dir, f"run_{ts}.txt")
    with open(out_file, "w", encoding="utf-8") as out_f:
        out_f.write(report)
    print(f"[SUMMARY] Saved run log to: {out_file}")

def main():
    slugs = get_live_movie_slugs()
    if not slugs:
        print("[ERROR] No movie slugs found to summarize.")
        return
    for slug in slugs:
        process_slug(slug)

if __name__ == "__main__":
    main()
