#!/usr/bin/env python3

import json
import os
from urllib.parse import urlparse

from ddgs import DDGS


PUBLISHERS_FILE = "publishers.json"
MOVIES_FILE = "data/movies/movies-live-today.json"
REVIEWS_DIR = "data/reviews"
OUTPUT_DIR = "data/searches"


def main():

    # -----------------------------
    # Load publishers
    # -----------------------------
    with open(PUBLISHERS_FILE, "r", encoding="utf-8") as f:
        publishers = json.load(f)

    # -----------------------------
    # Load today's movies
    # -----------------------------
    with open(MOVIES_FILE, "r", encoding="utf-8") as f:
        movies_data = json.load(f)

    # -----------------------------
    # Ensure output directory exists
    # -----------------------------
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with DDGS() as ddgs:

        for movie in movies_data["movies"]:

            movie_name = movie["name"]
            movie_slug = movie["slug"]

            print("\n" + "=" * 80)
            print(movie_name)
            print("=" * 80)

            # -----------------------------
            # Load existing review data if it exists to skip found publishers
            # -----------------------------
            completed_publishers = set()
            reviews_file_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
            if os.path.exists(reviews_file_path):
                try:
                    with open(reviews_file_path, "r", encoding="utf-8") as rf:
                        existing_review_data = json.load(rf)
                        for pub in existing_review_data.get("publishers", []):
                            if pub.get("review_url") and pub.get("review_url") != "NA":
                                completed_publishers.add(pub.get("publisher_id"))
                    print(f"Found existing review file. Skipping {len(completed_publishers)} already-resolved publishers.")
                except Exception as e:
                    print(f"Could not parse existing review file: {e}")

            # Also load existing search file if it exists so we don't wipe out previous results
            output_path = os.path.join(
                OUTPUT_DIR,
                f"search_{movie_slug}.json"
            )
            existing_search_publishers = {}
            if os.path.exists(output_path):
                try:
                    with open(output_path, "r", encoding="utf-8") as sf:
                        existing_search_data = json.load(sf)
                        for pub in existing_search_data.get("publishers", []):
                            existing_search_publishers[pub.get("publisher_id")] = pub
                except Exception:
                    pass

            output = {
                "movie": {
                    "name": movie_name,
                    "slug": movie_slug,
                    "date": movie.get("date")
                },
                "publishers": []
            }

            for publisher in publishers:

                if not publisher.get("active", False):
                    continue

                pub_id = publisher["id"]

                # If we already have a valid review URL from the review file, skip searching entirely
                if pub_id in completed_publishers:
                    print(f"Skipping {publisher['name']} (Review URL already found)")
                    # Keep existing search record if available
                    if pub_id in existing_search_publishers:
                        output["publishers"].append(existing_search_publishers[pub_id])
                    continue

                domain = urlparse(publisher["url"]).netloc.replace("www.", "")

                # -------------------------------------------------------------
                # QUERY 1: Standard Search (exact_match: false)
                # -------------------------------------------------------------
                query_broad = f'{movie_name} movie review site:{domain}'

                print(f"Searching {publisher['name']} (Broad)...")

                publisher_result = {
                    "publisher_id": publisher["id"],
                    "publisher_name": publisher["name"],
                    "publisher_url": publisher["url"],
                    "query": query_broad,
                    "results": []
                }

                try:
                    results_broad = list(ddgs.text(
                                        query_broad, 
                                        region="in-en",       
                                        backend="html",       
                                        max_results=5
                                    ))

                    for rank, r in enumerate(results_broad, start=1):
                        publisher_result["results"].append({
                            "rank": rank,
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                            "exact_match": False
                        })

                except Exception as e:
                    publisher_result["error"] = str(e)

                # -------------------------------------------------------------
                # QUERY 2: Exact Match Search (exact_match: true)
                # -------------------------------------------------------------
                query_exact = f'"{movie_name}" movie review site:{domain}'

                print(f"Searching {publisher['name']} (Exact Match)...")

                try:
                    results_exact = list(ddgs.text(
                                        query_exact, 
                                        region="in-en",       
                                        backend="html",       
                                        max_results=5
                                    ))
                # NEW: Catch the 0-results case and log it for CI/CD visibility
                    if not results_exact:
                        print(f"  [!] 0 exact match results for: {domain}")

                
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
                    if "error" not in publisher_result:
                        publisher_result["error"] = str(e)

                output["publishers"].append(publisher_result)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            print(f"Saved -> {output_path}")


if __name__ == "__main__":
    main()
