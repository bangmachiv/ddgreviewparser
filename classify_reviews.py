#!/usr/bin/env python3
"""
classify_reviews.py
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

    with open(movies_file, encoding="utf-8") as f:
        movies = json.load(f)["movies"]

    for movie in movies:
        slug = movie["slug"]
        search_file = os.path.join(searches_dir, f"search_{slug}.json")
        if not os.path.exists(search_file):
            continue

        print(f"\n================================================================================")
        print(f"Parsing Reviews for: {movie['name']}")
        print(f"================================================================================")

        with open(search_file, encoding="utf-8") as f:
            search_data = json.load(f)

        combos = generate_valid_combinations(
            get_movie_substrings(normalize_title(movie["name"]))
        )

        existing_classified_publishers = {}
        reviews_file_path = os.path.join(reviews_dir, f"reviews_{slug}.json")
        
        if os.path.exists(reviews_file_path):
            try:
                with open(reviews_file_path, "r", encoding="utf-8") as rf:
                    existing_data = json.load(rf)
                    for pub in existing_data.get("publishers", []):
                        if pub.get("review_url") and pub.get("review_url") != "NA":
                            existing_classified_publishers[pub["publisher_id"]] = pub
            except Exception as e:
                print(f"[WARNING] Could not parse existing reviews file for {slug}: {e}")

        reviews_output = {
            "movie": {
                "name": movie["name"],
                "slug": slug,
                "date": movie["date"]
            },
            "publishers": []
        }

        for pub in search_data.get("publishers", []):
            pub_id = pub.get("publisher_id", "")
            pub_name = pub.get("publisher_name", "")
            
            # 1. Skip if already locked in
            if pub_id in existing_classified_publishers:
                print(f"  [SKIP PARSING] {pub_name} already classified.")
                reviews_output["publishers"].append(existing_classified_publishers[pub_id])
                continue

            # 2. Log that we are actively evaluating this publisher
            print(f"  [EVALUATING] {pub_name}...")

            first = None
            for result in pub.get("results", []):
                ok = check_if_review(
                    result.get("title", ""),
                    result.get("url", ""),
                    combos
                )
                result["is_review"] = "Y" if ok else "N"
                if ok and first is None:
                    first = result

            # 3. Log the outcome of the evaluation
            if first:
                print(f"    -> [SUCCESS] Found valid review at Rank {first.get('rank')}")
            else:
                print(f"    -> [FAILED] No valid review titles found.")

            reviews_output["publishers"].append({
                "publisher_id": pub_id,
                "publisher_name": pub_name,
                "review_url": first.get("url", "NA") if first else "NA",
                "review_title": first.get("title", "NA") if first else "NA",
                "search_rank": first.get("rank", "NA") if first else "NA"
            })

        with open(search_file, "w", encoding="utf-8") as f:
            json.dump(search_data, f, ensure_ascii=False, indent=2)

        with open(reviews_file_path, "w", encoding="utf-8") as f:
            json.dump(reviews_output, f, ensure_ascii=False, indent=2)

        print(f"\nSuccessfully finished processing {slug}\n")

if __name__ == "__main__":
    main()

