#!/usr/bin/env python3

import json
import os
from urllib.parse import urlparse

from ddgs import DDGS


PUBLISHERS_FILE = "publishers.json"
MOVIES_FILE = "data/movies/movies-live-today.json"
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

                domain = urlparse(publisher["url"]).netloc.replace("www.", "")

                query = f'"{movie_name}" movie review site:{domain}'

                print(f"Searching {publisher['name']}")

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
                                    backend="html",       # Forces the HTML endpoint you verified in your browser
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

            output_path = os.path.join(
                OUTPUT_DIR,
                f"search_{movie_slug}.json"
            )

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            print(f"Saved -> {output_path}")


if __name__ == "__main__":
    main()
