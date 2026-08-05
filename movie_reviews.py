import json
from urllib.parse import urlparse
from ddgs import DDGS

movie_name = "Oppenheimer"

with open("publishers.json", "r", encoding="utf-8") as f:
    publishers = json.load(f)

with DDGS() as ddgs:
    for publisher in publishers:
        if not publisher.get("active", False):
            continue

        domain = urlparse(publisher["url"]).netloc

        # Changed query format
        query = f'{movie_name} movie review site:"{domain}"'

        print(f"\n=== {publisher['name']} ===")
        print(f"Query: {query}")

        try:
            # Fetch first 5 results instead of 1
            results = list(ddgs.text(query, max_results=5))

            if not results:
                print("No result found.")
                continue

            for i, r in enumerate(results, start=1):
                print(f"\nResult #{i}")
                print(f"Title: {r['title']}")
                print(f"URL: {r['href']}")

        except Exception as e:
            print(f"Search failed: {e}")
