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

            # Extract 4-digit release year from date field
            movie_date = movie.get("date", "")
            movie_year = movie_date[:4] if movie_date and len(movie_date) >= 4 else ""

            print("\n" + "=" * 80)
            print(f"{movie_name} ({movie_year})" if movie_year else movie_name)
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

                publisher_result = {
                    "publisher_id": publisher["id"],
                    "publisher_name": publisher["name"],
                    "publisher_url": publisher["url"],
                    "queries_used": {},
                    "query_status": {},
                    "results": []
                }

                seen_urls = set()
                current_rank = 1

                # -------------------------------------------------------------
                # QUERY 1: Generic with html label (Legacy Backend)
                # -------------------------------------------------------------
                type_1 = "Generic with html label"
                query_1 = f'{movie_name} {movie_year} movie review site:{domain}'.strip() if movie_year else f'{movie_name} movie review site:{domain}'
                publisher_result["queries_used"][type_1] = query_1

                print(f"Searching {publisher['name']} [{type_1}]...")
                try:
                    results_1 = list(ddgs.text(query_1, region="in-en", backend="html", max_results=5))
                    if not results_1:
                        print(f"  [!] 0 results for: {domain} ({type_1})")
                        publisher_result["query_status"][type_1] = "0 results"
                    else:
                        added = 0
                        for r in results_1:
                            url = r.get("href", "")
                            if url and url not in seen_urls:
                                publisher_result["results"].append({
                                    "rank": current_rank,
                                    "title": r.get("title", ""),
                                    "url": url,
                                    "snippet": r.get("body", ""),
                                    "exact_match": False,
                                    "search_type": type_1
                                })
                                seen_urls.add(url)
                                current_rank += 1
                                added += 1
                        publisher_result["query_status"][type_1] = f"Found {added} results"
                except Exception as e:
                    print(f"  [X] Error ({type_1}): {e}")
                    publisher_result["query_status"][type_1] = f"Error: {str(e)}"

                # -------------------------------------------------------------
                # QUERY 2: Generic without html label (Modern API)
                # -------------------------------------------------------------
                type_2 = "Generic without html label"
                # site: placed at the front for maximum modern API compatibility
                query_2 = f'site:{domain} {movie_name} {movie_year} movie review'.strip() if movie_year else f'site:{domain} {movie_name} movie review'
                publisher_result["queries_used"][type_2] = query_2

                print(f"Searching {publisher['name']} [{type_2}]...")
                try:
                    results_2 = list(ddgs.text(query_2, region="in-en", max_results=5))
                    if not results_2:
                        print(f"  [!] 0 results for: {domain} ({type_2})")
                        publisher_result["query_status"][type_2] = "0 results"
                    else:
                        added = 0
                        for r in results_2:
                            url = r.get("href", "")
                            if url and url not in seen_urls:
                                publisher_result["results"].append({
                                    "rank": current_rank,
                                    "title": r.get("title", ""),
                                    "url": url,
                                    "snippet": r.get("body", ""),
                                    "exact_match": False,
                                    "search_type": type_2
                                })
                                seen_urls.add(url)
                                current_rank += 1
                                added += 1
                        publisher_result["query_status"][type_2] = f"Found {added} new results"
                except Exception as e:
                    print(f"  [X] Error ({type_2}): {e}")
                    publisher_result["query_status"][type_2] = f"Error: {str(e)}"

                # -------------------------------------------------------------
                # QUERY 3: Specific without html label (Modern API)
                # -------------------------------------------------------------
                type_3 = "Specific without html label"
                # site: placed at the front, movie name inside quotes
                query_3 = f'site:{domain} "{movie_name}" {movie_year} movie review'.strip() if movie_year else f'site:{domain} "{movie_name}" movie review'
                publisher_result["queries_used"][type_3] = query_3

                print(f"Searching {publisher['name']} [{type_3}]...")
                try:
                    results_3 = list(ddgs.text(query_3, region="in-en", max_results=5))
                    if not results_3:
                        print(f"  [!] 0 results for: {domain} ({type_3})")
                        publisher_result["query_status"][type_3] = "0 results"
                    else:
                        added = 0
                        for r in results_3:
                            url = r.get("href", "")
                            if url and url not in seen_urls:
                                publisher_result["results"].append({
                                    "rank": current_rank,
                                    "title": r.get("title", ""),
                                    "url": url,
                                    "snippet": r.get("body", ""),
                                    "exact_match": True,
                                    "search_type": type_3
                                })
                                seen_urls.add(url)
                                current_rank += 1
                                added += 1
                        publisher_result["query_status"][type_3] = f"Found {added} new results"
                except Exception as e:
                    print(f"  [X] Error ({type_3}): {e}")
                    publisher_result["query_status"][type_3] = f"Error: {str(e)}"

                output["publishers"].append(publisher_result)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            print(f"Saved -> {output_path}")


if __name__ == "__main__":
    main()
