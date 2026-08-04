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
        query = f"{movie_name} site:{domain} movie review"

        print(f"\n=== {publisher['name']} ===")
        print(f"Query: {query}")

        try:
            results = list(ddgs.text(query, max_results=1))

            if results:
                r = results[0]
                print(f"Title: {r['title']}")
                print(f"URL: {r['href']}")
            else:
                print("No result found.")

        except Exception as e:
            print(f"Search failed: {e}")
