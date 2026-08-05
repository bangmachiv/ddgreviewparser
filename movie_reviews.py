import json
import os
from urllib.parse import urlparse
from ddgs import DDGS

# -----------------------------
# Load publishers
# -----------------------------
with open("publishers.json", "r", encoding="utf-8") as f:
    publishers = json.load(f)

# -----------------------------
# Load today's movies
# -----------------------------
with open("data/movies/movies-live-today.json", "r", encoding="utf-8") as f:
    movies_data = json.load(f)

# -----------------------------
# Ensure output directory exists
# -----------------------------
os.makedirs("data/searches", exist_ok=True)

# -----------------------------
# Search
# -----------------------------
with DDGS() as ddgs:

    for movie in movies_data["movies"]:

        movie_name = movie["name"]
        movie_slug = movie["slug"]

        print(f"\n{'='*80}")
        print(movie_name)
        print(f"{'='*80}")

        output = {
            "movie": movie_name,
            "slug": movie_slug,
            "searches": []
        }

        for publisher in publishers:

            if not publisher.get("active", False):
                continue

            domain = urlparse(publisher["url"]).netloc

            query = f'{movie_name} movie review site:"{domain}"'

            print(f"Searching {publisher['name']}")

            publisher_result = {
                "publisher_id": publisher["id"],
                "publisher_name": publisher["name"],
                "publisher_url": publisher["url"],
                "query": query,
                "results": []
            }

            try:

                results = list(ddgs.text(query, max_results=5))

                for rank, r in enumerate(results, start=1):
                    publisher_result["results"].append({
                        "rank": rank,
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")
                    })

            except Exception as e:
                publisher_result["error"] = str(e)

            output["searches"].append(publisher_result)

        output_path = f"data/searches/search_{movie_slug}.json"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"Saved -> {output_path}")
