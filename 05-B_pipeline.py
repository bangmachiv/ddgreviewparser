#!/usr/bin/env python3
"""
05-B_pipeline.py
Collects metrics from logs and reviews data to produce:
  1. A tabular per-script execution table (HadToDo, Processed, Failure, Success).
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
    ("03_download", "03_download.json"),
    ("04-A-1_titles", "04-A-1_titles.json"),
    ("04-A-2_clean", "04-A-2_clean.json"),
    ("04-A-3_highlight", "04-A-3_highlight.json"),
    ("04-B-1_metadata-jsonld", "04-B-1_metadata-jsonld.json"),
    ("04-B-2_metadata-ai", "04-B-2_metadata-ai.json"),
    ("04-B-3_label", "04-B-3_label.json"),
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

def extract_latest_log_metrics(log_path):
    if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
        return None
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return None
        latest_ts = sorted(data.keys())[-1]
        run = data[latest_ts]
        had_to_do = run.get("earlier_pending", run.get("processed", 0))
        processed = run.get("processed", 0)
        failure = run.get("failure", 0)
        success = run.get("success", 0)
        return had_to_do, processed, failure, success
    except Exception:
        return None

def process_slug(slug):
    movie_logs_dir = os.path.join(LOGS_DIR, f"logs_{slug}")
    review_path = os.path.join(REVIEWS_DIR, f"reviews_{slug}.json")

    # --- 1. Tabular Execution Data ---
    stage_rows = []
    for idx, (stage_name, log_filename) in enumerate(PIPELINE_STAGES, start=1):
        log_file = os.path.join(movie_logs_dir, log_filename)
        metrics = extract_latest_log_metrics(log_file)
        if metrics:
            had, proc, fail, succ = metrics
            stage_rows.append(f"{idx:<2}. {stage_name:<24} | {had:>7} | {proc:>9} | {fail:>7} | {succ:>7}")
        else:
            stage_rows.append(f"{idx:<2}. {stage_name:<24} |       - |         - |       - |       -")

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

    if os.path.exists(review_path):
        with open(review_path, "r", encoding="utf-8") as f:
            rdata = json.load(f)

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
    output_lines.append("=" * 68)
    output_lines.append(f" PIPELINE EXECUTION SUMMARY: {slug}")
    output_lines.append("=" * 68)
    output_lines.append(f"{'Script No & Name':<28} | {'HadToDo':>7} | {'Processed':>9} | {'Failure':>7} | {'Success':>7}")
    output_lines.append("-" * 68)
    output_lines.extend(stage_rows)
    output_lines.append("")
    output_lines.append("=" * 68)
    output_lines.append(" FINAL NEWS STATUS")
    output_lines.append("=" * 68)
    for label, count in status_counts.items():
        output_lines.append(f"{label:<22}: {count}")
    output_lines.append("=" * 68)

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
