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
            print(f"Processing: {movie_name}")
            print("=" * 80)

            # -----------------------------
            # FILTER LOGIC: Find missing publishers
            # -----------------------------
            reviews_file_path = os.path.join(REVIEWS_DIR, f"reviews_{movie_slug}.json")
            
            # Skip if the classification file doesn't exist yet
            if not os.path.exists(reviews_file_path):
                print(f"No classified reviews file found for {movie_slug}. Skipping.")
                continue
                
            with open(reviews_file_path, "r", encoding="utf-8") as rf:
                classified_data = json.load(rf)
                
            # Collect publisher IDs where the review URL is "NA"
            na_publishers = set()
            for pub in classified_data.get("publishers", []):
                if pub.get("review_url") == "NA":
                    na_publishers.add(pub.get("publisher_id"))
            
            # If the set is empty, all reviews were found. Skip the movie entirely.
            if not na_publishers:
                print("All reviews already found for this movie. Skipping secondary search.")
                continue
                
            print(f"Found {len(na_publishers)} publishers missing reviews. Starting targeted search...")

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

                # -----------------------------
                # Skip publishers that already have a review
                # -----------------------------
                if publisher["id"] not in na_publishers:
                    continue

                domain = urlparse(publisher["url"]).netloc.replace("www.", "")

                # Implemented the strict exact-match query string
                query = f'"{movie_name}" site:{domain}'

                print(f"Searching {publisher['name']} (Missing URL)...")

                publisher_result = {
                    "publisher_id": publisher["id"],
                    "publisher_name": publisher["name"],
                    "publisher_url": publisher["url"],
                    "query": query,
                    "results": []
                }

                try:

                    results = list(ddgs.text(
                                    query, 
                                    region="in-en",       # Forces Indian localized results
                                    backend="html",       # Forces the HTML endpoint
                                    max_results=5
                                ))

                    for rank, r in enumerate(results, start=1):

                        publisher_result["results"].append({
                            "rank": rank,
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", "")
                        })

                except Exception as e:

                    publisher_result["error"] = str(e)

                output["publishers"].append(publisher_result)

            # Saving to a distinct "second_search_" file so it doesn't overwrite the primary run
            output_path = os.path.join(
                OUTPUT_DIR,
                f"second_search_{movie_slug}.json"
            )

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            print(f"Saved -> {output_path}")


if __name__ == "__main__":
    main()
