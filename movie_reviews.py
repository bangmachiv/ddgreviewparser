#!/usr/bin/env python3

import argparse
from ddgs import DDGS


def search(query: str, max_results: int = 10):
    print(f"Searching: {query}\n")

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            print("No results found.")
            return

        for i, result in enumerate(results, start=1):
            print("=" * 80)
            print(f"Result #{i}")
            print(f"Title   : {result.get('title', '')}")
            print(f"URL     : {result.get('href', '')}")
            print(f"Snippet : {result.get('body', '')}")

    except Exception as e:
        print(f"Search failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="DuckDuckGo Search")
    parser.add_argument(
        "--query",
        required=True,
        help="Search query"
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Maximum number of search results"
    )

    args = parser.parse_args()
    search(args.query, args.max_results)


if __name__ == "__main__":
    main()
