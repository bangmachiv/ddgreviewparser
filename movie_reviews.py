import json
import re
from urllib.parse import urlparse
from ddgs import DDGS

movie_name = "Oppenheimer"

# -----------------------------
# Build whitelist
# -----------------------------

STATIC_WHITELIST = {
    "movie",
    "film",
    "review",
    "मूवी",
    "फिल्म",
    "रिव्यू",
    "समीक्षा",
}

clean_movie_name = re.sub(r"[^A-Za-z0-9 ]+", " ", movie_name)
clean_movie_name = " ".join(clean_movie_name.split()).lower()

movie_words = set(clean_movie_name.split())

WHITELIST = STATIC_WHITELIST | movie_words

print("Whitelist:", sorted(WHITELIST))
print()

# -----------------------------
# Load publishers
# -----------------------------

with open("publishers.json", "r", encoding="utf-8") as f:
    publishers = json.load(f)

# -----------------------------
# Search
# -----------------------------

with DDGS() as ddgs:

    for publisher in publishers:

        if not publisher.get("active", False):
            continue

        domain = urlparse(publisher["url"]).netloc

        query = f'{movie_name} movie review site:"{domain}"'

        print("=" * 100)
        print(publisher["name"])
        print(query)

        try:

            results = list(ddgs.text(query, max_results=5))

            if not results:
                print("No results")
                print()
                continue

            matched = False

            for i, r in enumerate(results, start=1):

                title = r["title"]
                url = r["href"]

                print(f"\nResult {i}")
                print(title)
                print(url)

                # -----------------------------
                # Whitelist check
                # -----------------------------

                if ":" not in title:
                    continue

                prefix = title.split(":", 1)[0]

                prefix_clean = re.sub(
                    r"[^\w\u0900-\u097F ]+",
                    " ",
                    prefix.lower()
                )

                prefix_clean = " ".join(prefix_clean.split())

                words = prefix_clean.split()

                if words and all(word in WHITELIST for word in words):
                    print("✅ WHITELIST MATCH")
                    matched = True
                    break

            if not matched:
                print("\n❌ No whitelist match")

            print()

        except Exception as e:
            print("Search failed:", e)
            print()
