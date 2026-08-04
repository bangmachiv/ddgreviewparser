import argparse
from duckduckgo_search import DDGS


def search(query, max_results=10):
    print(f"Searching: {query}\n")

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--query",
        required=True,
        help="Search query"
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10
    )

    args = parser.parse_args()

    search(args.query, args.max_results)
