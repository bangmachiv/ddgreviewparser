import json
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/138.0.0.0 Safari/537.36"
    )
}


def fetch_html(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def load_jsonld_blocks(html):
    soup = BeautifulSoup(html, "html.parser")

    blocks = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = script.string or script.get_text()
        if not text:
            continue

        try:
            blocks.append(json.loads(text))
        except Exception:
            # Ignore malformed JSON-LD
            pass

    return blocks


def recursive_extract(node):
    """
    Recursively searches all JSON-LD objects.

    Returns:
        (critic_name, star_rating)

    Preference:
    - If an object has reviewRating.ratingValue, use its author.name.
    - Otherwise continue searching.
    """

    if isinstance(node, dict):

        # Pattern 1
        # {
        #   "@type":"Review",
        #   "author":...
        #   "reviewRating":...
        # }

        if isinstance(node.get("reviewRating"), dict):

            rating = node["reviewRating"].get("ratingValue")

            author = None

            if isinstance(node.get("author"), dict):
                author = node["author"].get("name")

            elif isinstance(node.get("author"), list):
                if node["author"]:
                    author = node["author"][0].get("name")

            if rating is not None:
                return author, rating

        # Continue recursion
        for value in node.values():
            critic, rating = recursive_extract(value)
            if rating is not None:
                return critic, rating

    elif isinstance(node, list):

        for item in node:
            critic, rating = recursive_extract(item)
            if rating is not None:
                return critic, rating

    return None, None


def extract_review_metadata(html):
    jsonlds = load_jsonld_blocks(html)

    for block in jsonlds:
        critic, rating = recursive_extract(block)

        if critic is not None or rating is not None:
            return critic, rating

    return None, None


def process_movie_json(path):
    path = Path(path)

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Adjust this depending on your JSON structure
    publishers = data if isinstance(data, list) else data.get("reviews", [])

    for pub in publishers:

        url = pub.get("review_url")

        if not url:
            continue

        print(f"Processing: {url}")

        try:
            html = fetch_html(url)

            critic, rating = extract_review_metadata(html)

            pub["critic_name"] = critic
            pub["star_rating"] = rating

            print(
                f"  critic={critic!r}  rating={rating!r}"
            )

        except Exception as e:
            print(f"  ERROR: {e}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Usage:")
        print("python extract_jsonld.py data/reviews/2026-alpha.json")
        sys.exit(1)

    process_movie_json(sys.argv[1])
