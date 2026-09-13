#!/usr/bin/env python3
"""
05-B_json_summary.py
Extracts a clean, finalized JSON summary for each active movie.
Filters out pending/failed publishers and cascades ratings and critic names.
Outputs to: data/output/json/summary_<slug>.json
"""

import json
import os
import glob

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REVIEWS_DIR = os.path.join(BASE_DIR, "data", "reviews")
MOVIES_FILE = os.path.join(BASE_DIR, "data", "movies", "movies-live-today.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "output", "json")

VALID_CATEGORIES = ["GOOD", "NEUTRAL", "BAD", "POSITIVE", "MIXED", "NEGATIVE"]
BAD_VALUES = [None, "", "NA", "Na", "null", "FAILED", "PENDING", "NOT_NEEDED"]

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
def parse_rating(val):
    if val in BAD_VALUES or "could not find" in str(val).lower():
        return None
    try:
        return float(val)
    except ValueError:
        return None

def parse_critic(val):
    if val in BAD_VALUES or str(val).strip().upper() in BAD_VALUES:
        return ""
    return str(val).strip()

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
        # Fallback: process all reviews if live file is missing
        for p in glob.glob(os.path.join(REVIEWS_DIR, "reviews_*.json")):
            base = os.path.basename(p)
            slugs.append(base.replace("reviews_", "").replace(".json", ""))
    return list(set(slugs))

# -----------------------------------------------------------------------------
# Main Extraction Logic
# -----------------------------------------------------------------------------
def process_movie_summary(slug):
    review_path = os.path.join(REVIEWS_DIR, f"reviews_{slug}.json")
    
    if not os.path.exists(review_path):
        print(f"[WARN] No review file found for {slug}. Skipping.")
        return

    with open(review_path, "r", encoding="utf-8") as f:
        rdata = json.load(f)

    movie = rdata.get("movie", {})
    movie_name = str(movie.get("name", "Unknown Movie")).strip()
    release_date = str(movie.get("date", "Unknown Date")).strip()

    summary_data = {
        "movie_name": movie_name,
        "release_date": release_date,
        "publishers": []
    }

    for pub in rdata.get("publishers", []):
        # 1. Parse Potential Rating Data
        ld_rating = parse_rating(pub.get("jsonld_star_rating"))
        ai_rating = parse_rating(pub.get("ai_star_rating"))
        ai_cat = str(pub.get("ai_sentiment_category", "")).strip().upper()
        
        valid_cat = ai_cat in VALID_CATEGORIES

        # 2. Skip if absolutely no rating data exists
        if ld_rating is None and ai_rating is None and not valid_cat:
            continue

        # 3. Cascade Rating & Source
        if ld_rating is not None:
            final_rating = ld_rating
            rating_source = "JSONLD"
        elif ai_rating is not None:
            final_rating = ai_rating
            rating_source = "AI_HTML"
        else:
            final_rating = ai_cat
            rating_source = "AI_LABEL"

        # 4. Cascade Critic
        ld_critic = parse_critic(pub.get("jsonld_critic_name"))
        ai_critic = parse_critic(pub.get("ai_critic_name"))
        final_critic = ld_critic if ld_critic else ai_critic

        # 5. Get Best Available Review Title
        review_title = str(pub.get("clean_title", "")).strip()
        if review_title in BAD_VALUES:
            review_title = str(pub.get("article_title", "")).strip()
            if review_title in BAD_VALUES:
                review_title = ""

        # 6. Append to Summary
        summary_data["publishers"].append({
            "Name": str(pub.get("publisher_name", "")).strip(),
            "Review": review_title,
            "Rating": final_rating,
            "Critic": final_critic,
            "URL": str(pub.get("review_url", "")).strip(),
            "Rating_Source": rating_source
        })

    # 7. Save the Output JSON
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"summary_{slug}.json")
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=4, ensure_ascii=False)
        
    print(f"[SUCCESS] Saved JSON summary for {slug} with {len(summary_data['publishers'])} valid publishers.")

def main():
    print("=" * 60)
    print(" 05-B - GENERATING JSON SUMMARIES")
    print("=" * 60)
    
    slugs = get_live_movie_slugs()
    if not slugs:
        print("[ERROR] No movie slugs found to process.")
        return
        
    for slug in slugs:
        process_movie_summary(slug)
        
    print("=" * 60)

if __name__ == "__main__":
    main()
