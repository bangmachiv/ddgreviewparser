#!/usr/bin/env python3

import logging
import time
import traceback
from ddgs import DDGS

# Enable deep network debugging to trace exactly which fallback engines it uses
logging.basicConfig(level=logging.DEBUG)

MAX_RETRIES = 3
RETRY_DELAY = 3


def search_with_retries(ddgs_client, query: str, max_results: int = 5):
    """Executes search using the default 'auto' backend with incremental retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n---> Executing Attempt {attempt}/{MAX_RETRIES} for query: {query}")
        try:
            # Note: The backend parameter is intentionally omitted here.
            # This forces the library into 'auto' mode, bypassing DuckDuckGo firewalls.
            results = list(
                ddgs_client.text(
                    query,
                    region="in-en",
                    max_results=max_results,
                )
            )
            if results:
                return results, None
            print(f"     [!] 0 results returned on attempt {attempt}.")
        except Exception as exc:
            print(f"     [!] Exception caught on attempt {attempt}: {exc}")
            traceback.print_exc()

        if attempt < MAX_RETRIES:
            wait_time = attempt * RETRY_DELAY
            print(f"     Waiting {wait_time}s before next attempt...")
            time.sleep(wait_time)

    return [], "Max retries reached with 0 results or errors."


def main():
    movie_name = "Bhai Tera Star Hai"
    domain = "bollywoodhungama.com"

    query_broad = f"{movie_name} movie review site:{domain}"
    query_exact = f'"{movie_name}" movie review site:{domain}'

    print("=" * 80)
    print(" DIAGNOSTIC TEST: BACKEND='AUTO' (FALLBACK) MULTI-ATTEMPT TEST")
    print(f" Target Domain: {domain}")
    print(f" Target Movie : {movie_name}")
    print("=" * 80)

    with DDGS(timeout=30) as ddgs:
        # TEST 1: BROAD SEARCH
        print("\n" + "=" * 50)
        print(" [TEST 1] BROAD SEARCH QUERY")
        print("=" * 50)
        results_broad, err_broad = search_with_retries(ddgs, query_broad, max_results=5)
        print(f"\n[SUMMARY 1] Broad Search Results Count: {len(results_broad)}")
        for idx, item in enumerate(results_broad, start=1):
            print(f"  {idx}. Title: {item.get('title')}")
            print(f"     URL  : {item.get('href')}")
            print(f"     Text : {item.get('body')}\n")

        time.sleep(3)  # Cooldown between tests

        # TEST 2: EXACT SEARCH
        print("\n" + "=" * 50)
        print(" [TEST 2] EXACT MATCH SEARCH QUERY")
        print("=" * 50)
        results_exact, err_exact = search_with_retries(ddgs, query_exact, max_results=5)
        print(f"\n[SUMMARY 2] Exact Match Results Count: {len(results_exact)}")
        for idx, item in enumerate(results_exact, start=1):
            print(f"  {idx}. Title: {item.get('title')}")
            print(f"     URL  : {item.get('href')}")
            print(f"     Text : {item.get('body')}\n")


if __name__ == "__main__":
    main()
