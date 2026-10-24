
#!/usr/bin/env python3

"""
DDGS SEARCH BACKEND DIAGNOSTIC
Designed for GitHub Actions.

Tests multiple query styles across multiple search
backends and prints up to 10 results per search.

No API key required.
"""

import os
import sys
import time
import logging
import traceback
import platform
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError

from ddgs import DDGS


# ============================================================
# CONFIGURATION
# ============================================================

MAX_RESULTS = 10
MAX_RETRIES = 2
RETRY_DELAY = 3
QUERY_COOLDOWN = 5
REQUEST_TIMEOUT = 25

REGION = "in-en"

# Override through GitHub Actions environment variables.
MAX_RESULTS = int(os.getenv("MAX_RESULTS", MAX_RESULTS))
QUERY_COOLDOWN = float(
    os.getenv("QUERY_COOLDOWN", QUERY_COOLDOWN)
)

BACKENDS = [
    "duckduckgo",
    "brave",
    "bing",
    "google",
    "yahoo",
    "auto",
]

MOVIE_NAME = "Bhai Tera Star Hai"
MOVIE_YEAR = "2026"

SEARCH_QUERIES = [
    {
        "id": "Q1",
        "type": "General Connectivity",
        "query": "Python programming language",
    },
    {
        "id": "Q2",
        "type": "General Movie Review",
        "query": "Dangal movie review",
    },
    {
        "id": "Q3",
        "type": "Exact Movie Title",
        "query": '"Dangal" movie review',
    },
    {
        "id": "Q4",
        "type": "Exact Title With Year",
        "query": '"Dangal" 2016 movie review',
    },
    {
        "id": "Q5",
        "type": "Publisher-Specific Review",
        "query": (
            '"Dangal" movie review '
            "site:hindustantimes.com"
        ),
    },
    {
        "id": "Q6",
        "type": "Target Movie Exact Search",
        "query": (
            f'"{MOVIE_NAME}" '
            f"{MOVIE_YEAR} movie review"
        ),
    },
]


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)

logger = logging.getLogger("ddgs-diagnostic")


def separator(char="=", length=90):
    print(char * length, flush=True)


def package_version():
    try:
        return version("ddgs")
    except PackageNotFoundError:
        return "Unknown"


# ============================================================
# SEARCH FUNCTION
# ============================================================

def execute_search(query, backend):
    """
    Run one search with retries.

    Returns:
        {
            status: SUCCESS / EMPTY / ERROR,
            results: list,
            elapsed: float,
            attempts: int,
            error: str or None
        }
    """

    last_error = None
    total_start = time.perf_counter()

    for attempt in range(1, MAX_RETRIES + 1):

        logger.info(
            "Search attempt %s/%s | backend=%s",
            attempt,
            MAX_RETRIES,
            backend,
        )

        try:
            # Fresh client for each attempt.
            with DDGS(timeout=REQUEST_TIMEOUT) as client:
                results = list(
                    client.text(
                        query,
                        region=REGION,
                        safesearch="moderate",
                        max_results=MAX_RESULTS,
                        backend=backend,
                    )
                )

            elapsed = time.perf_counter() - total_start

            if results:
                return {
                    "status": "SUCCESS",
                    "results": results,
                    "elapsed": elapsed,
                    "attempts": attempt,
                    "error": None,
                }

            logger.warning(
                "Backend %s returned zero results",
                backend,
            )

            last_error = "Empty results"

        except Exception as exc:

            last_error = (
                f"{type(exc).__name__}: {exc}"
            )

            logger.error(
                "SEARCH ERROR | backend=%s | attempt=%s",
                backend,
                attempt,
            )

            logger.error(last_error)
            traceback.print_exc(file=sys.stdout)

        if attempt < MAX_RETRIES:
            delay = RETRY_DELAY * attempt

            logger.info(
                "Retrying after %s seconds",
                delay,
            )

            time.sleep(delay)

    elapsed = time.perf_counter() - total_start

    status = (
        "EMPTY"
        if last_error == "Empty results"
        else "ERROR"
    )

    return {
        "status": status,
        "results": [],
        "elapsed": elapsed,
        "attempts": MAX_RETRIES,
        "error": last_error,
    }


# ============================================================
# PRINT RESULTS
# ============================================================

def print_search_results(outcome):

    separator("-")

    print(f"STATUS       : {outcome['status']}")
    print(f"RESULT COUNT : {len(outcome['results'])}")
    print(f"ELAPSED TIME : {outcome['elapsed']:.2f}s")
    print(f"ATTEMPTS     : {outcome['attempts']}")

    if outcome["error"]:
        print(f"ERROR        : {outcome['error']}")

    if outcome["results"]:

        print("\nSEARCH RESULTS:")

        for index, result in enumerate(
            outcome["results"][:MAX_RESULTS],
            start=1,
        ):

            print(f"\n  RESULT {index}")
            print(f"  Title   : {result.get('title', '')}")
            print(f"  URL     : {result.get('href', '')}")
            print(f"  Snippet : {result.get('body', '')}")

    separator("-")


# ============================================================
# MAIN
# ============================================================

def main():

    separator()

    print("DDGS MULTI-BACKEND SEARCH DIAGNOSTIC")

    separator()

    print(
        "UTC TIME       :",
        datetime.now(timezone.utc).isoformat(),
    )
    print("PYTHON VERSION :", platform.python_version())
    print("DDGS VERSION   :", package_version())
    print("REGION         :", REGION)
    print("RESULTS/SEARCH :", MAX_RESULTS)
    print("RETRIES        :", MAX_RETRIES)
    print("COOLDOWN       :", QUERY_COOLDOWN)

    print("\nBACKENDS:")
    for backend in BACKENDS:
        print(f"  - {backend}")

    print("\nSEARCH QUERIES:")
    for item in SEARCH_QUERIES:
        print(f"  {item['id']}: {item['query']}")

    total_tests = len(BACKENDS) * len(SEARCH_QUERIES)

    print(f"\nTOTAL TESTS: {total_tests}")

    separator()

    summary = []

    test_number = 0

    # Group by backend for easier comparison.
    for backend in BACKENDS:

        separator("#")

        print(f"TESTING BACKEND: {backend.upper()}")

        separator("#")

        for query_item in SEARCH_QUERIES:

            test_number += 1

            query = query_item["query"]

            print()
            separator("=")

            print(
                f"TEST {test_number}/{total_tests}"
            )

            print(f"BACKEND     : {backend}")
            print(f"QUERY ID    : {query_item['id']}")
            print(f"QUERY TYPE  : {query_item['type']}")
            print(f"QUERY       : {query}")

            separator("=")

            outcome = execute_search(
                query=query,
                backend=backend,
            )

            print_search_results(outcome)

            summary.append({
                "backend": backend,
                "query_id": query_item["id"],
                "status": outcome["status"],
                "count": len(outcome["results"]),
                "seconds": outcome["elapsed"],
                "error": outcome["error"],
            })

            # Polite cooldown to reduce throttling.
            if test_number < total_tests:
                logger.info(
                    "Cooldown: %.1f seconds",
                    QUERY_COOLDOWN,
                )

                time.sleep(QUERY_COOLDOWN)

    # ========================================================
    # FINAL TEST SUMMARY
    # ========================================================

    print()
    separator("=")

    print("FINAL TEST SUMMARY")

    separator("=")

    header = (
        f"{'BACKEND':<15}"
        f"{'QUERY':<8}"
        f"{'STATUS':<12}"
        f"{'RESULTS':<10}"
        f"{'SECONDS':<10}"
    )

    print(header)
    separator("-")

    for item in summary:

        print(
            f"{item['backend']:<15}"
            f"{item['query_id']:<8}"
            f"{item['status']:<12}"
            f"{item['count']:<10}"
            f"{item['seconds']:<10.2f}"
        )

    separator("=")

    print("\nBACKEND-WISE SUMMARY:")

    for backend in BACKENDS:

        backend_tests = [
            item for item in summary
            if item["backend"] == backend
        ]

        success = sum(
            item["status"] == "SUCCESS"
            for item in backend_tests
        )

        empty = sum(
            item["status"] == "EMPTY"
            for item in backend_tests
        )

        errors = sum(
            item["status"] == "ERROR"
            for item in backend_tests
        )

        total_results = sum(
            item["count"]
            for item in backend_tests
        )

        avg_seconds = (
            sum(item["seconds"] for item in backend_tests)
            / len(backend_tests)
        )

        print(f"\n{backend.upper()}")
        print(f"  Successful Searches : {success}")
        print(f"  Empty Searches      : {empty}")
        print(f"  Failed Searches     : {errors}")
        print(f"  Total Results       : {total_results}")
        print(f"  Average Time        : {avg_seconds:.2f}s")

    separator("=")

    total_success = sum(
        item["status"] == "SUCCESS"
        for item in summary
    )

    total_errors = sum(
        item["status"] == "ERROR"
        for item in summary
    )

    total_empty = sum(
        item["status"] == "EMPTY"
        for item in summary
    )

    print("\nOVERALL RESULT")
    print(f"Total Tests : {total_tests}")
    print(f"Successful  : {total_success}")
    print(f"Empty       : {total_empty}")
    print(f"Errors      : {total_errors}")

    separator("=")

    # Fail the GitHub Actions job only if every search failed
    # to produce results.
    if total_success == 0:
        logger.error(
            "No backend produced successful search results."
        )
        return 1

    logger.info(
        "Diagnostic completed. At least one search succeeded."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
