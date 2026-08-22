#!/usr/bin/env python3
"""
02_identify.py
"""

import os
import json
from urllib.parse import urlparse, parse_qs

REVIEW_PHRASES = [
    "review",
    "movie review",
    "film review",
    "hindi review",
    "hindi movie review",
    "रिव्यू",
    "समीक्षा",
    "मूवी रिव्यू",
    "मूवी समीक्षा",
    "फिल्म रिव्यू",
    "फिल्म समीक्षा",
    "हिंदी रिव्यू"
]

NEGATIVE_PHRASES = [
    "compilation", "roundup", "video", "podcast", "twitter", "reddit",
    "explained", "ending explained", "ending", "analysis", "breakdown",
    "box office", "collection", "trailer", "teaser", "cast", "songs",
    "soundtrack", "ott", "streaming", "preview", "first look", "featurette",
    "reaction", "reactions", "news", "live updates"
]

def is_video_url(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    parsed = urlparse(url_lower)
    if "/video/" in parsed.path:
        return True
    if parsed.path.rstrip("/").endswith("/video"):
        return True
    query_params = parse_qs(parsed.query)
    if "video" in query_params.get("type", []):
        return True
    return False

def normalize_title(title: str) -> str:
    if not title:
        return ""
    title = title.lower()
    out = []
    for ch in title:
        out.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return " ".join("".join(out).split())

def get_movie_substrings(normalized_name: str):
    words = normalized_name.split()
    return [" ".join(words[:i]) for i in range(1, len(words) + 1)]

def generate_valid_combinations(movie_substrings):
    combos = set()
    for sub in movie_substrings:
        for phrase in REVIEW_PHRASES:
            combos.add(f"{sub} {phrase}")
            combos.add(f"{phrase} {sub}")
    return sorted(combos, key=len, reverse=True)

def check_if_review(title: str, url: str, valid_combos: list) -> bool:
    if is_video_url(url):
        return False
    norm_title = normalize_title(title)
    padded = f" {norm_title} "
    for neg in NEGATIVE_PHRASES:
        if f" {neg} " in padded:
            return False
    for combo in valid_combos:
        if norm_title == combo or norm_title.startswith(combo + " "):
            return True
    return False

def main():
    base = os.path.dirname(os.path.abspath(__file__))
    movies_file = os.path.join(base, "data", "movies", "movies-live-today.json")
    searches_dir = os.path.join(base, "data", "searches")
    reviews_dir = os.path.join(base, "data", "reviews")
    
    os.makedirs(reviews_dir, exist_ok=True)

    if not os.path.exists(movies_file):
        print(f"[FATAL] {movies_file} not found.")
        return

    with open(movies_file, encoding="utf-8") as f:
        movies = json.load(f)["movies"]

    for movie in movies:
        slug = movie["slug"]
        search_file = os.path.join(searches_dir, f"searches_{slug}.json")
        reviews_file_path = os.path.join(reviews_dir, f"reviews_{slug}.json")

        # Skip if previous pipeline steps haven't generated the required files
        if not os.path.exists(search_file) or not os.path.exists(reviews_file_path):
            continue

        print(f"\n================================================================================")
        print(f" Parsing Reviews for: {movie['name']}")
        print(f"================================================================================")

        with open(search_file, encoding="utf-8") as f:
            search_data = json.load(f)

        with open(reviews_file_path, "r", encoding="utf-8") as f:
            reviews_data = json.load(f)

        combos = generate_valid_combinations(
            get_movie_substrings(normalize_title(movie["name"]))
        )

        # Create a dictionary of the search results for easy lookup by publisher_id
        search_results_map = {pub.get("publisher_id"): pub for pub in search_data.get("publishers", [])}

        # Modify the reviews_data IN-PLACE to preserve the 17-field Master Skeleton
        for pub_block in reviews_data.get("publishers", []):
            pub_id = pub_block.get("publisher_id", "")
            pub_name = pub_block.get("publisher_name", "")

            # 1. Skip if already locked in
            current_url = pub_block.get("review_url", "PENDING")
            if current_url not in ["PENDING", "NA", ""]:
                print(f"  [SKIP PARSING] {pub_name} already classified.")
                continue

            # 2. Skip if no new search results exist for this publisher
            if pub_id not in search_results_map:
                continue

            print(f"  [EVALUATING] {pub_name}...")
            search_pub_data = search_results_map[pub_id]

            first = None
            for result in search_pub_data.get("results", []):
                ok = check_if_review(
                    result.get("title", ""),
                    result.get("url", ""),
                    combos
                )
                
                # Appends the audit trail directly into the searches_ data object
                result["is_review"] = "Y" if ok else "N"
                
                # Lock in the highest ranked valid review
                if ok and first is None:
                    first = result

            # 3. Log the outcome and update the Master Skeleton block
            if first:
                rank = first.get('rank')
                print(f"    -> [SUCCESS] Found valid review at Rank {rank}")
                pub_block["review_url"] = first.get("url", "NA")
                pub_block["review_title"] = first.get("title", "NA")
                pub_block["review_source"] = f"ddgs_{rank}"
                pub_block["search_status"] = "NOT_NEEDED"
            else:
                print(f"    -> [FAILED] No valid review titles found.")
                # Ensure fields remain PENDING so the search script retries them next run
                pub_block["review_url"] = "PENDING"
                pub_block["review_title"] = "PENDING"
                pub_block["review_source"] = "PENDING"
                pub_block["search_status"] = "PENDING"

        # Save the audited search data
        with open(search_file, "w", encoding="utf-8") as f:
            json.dump(search_data, f, ensure_ascii=False, indent=4)

        # Save the preserved and updated review skeleton
        with open(reviews_file_path, "w", encoding="utf-8") as f:
            json.dump(reviews_data, f, ensure_ascii=False, indent=4)

        print(f"\n Successfully finished processing {slug}\n")

if __name__ == "__main__":
    main()
