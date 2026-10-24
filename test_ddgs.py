
#!/usr/bin/env python3

"""
DDGS MOVIE REVIEW SEARCH DIAGNOSTIC

Designed for GitHub Actions.

Focus:
1. Yahoo, Startpage, DuckDuckGo
2. Movie-review URL discovery
3. Publisher-specific site searches
4. Backend reliability
5. Result quality and malformed titles

Prints up to 10 results per search.
Saves detailed JSON report.
"""

import os
import sys
import json
import time
import logging
import traceback
from datetime import datetime, timezone
from urllib.parse import urlparse
from importlib.metadata import version

from ddgs import DDGS


# ============================================================
# CONFIGURATION
# ============================================================

BACKENDS = [
    "yahoo",
    "startpage",
    "duckduckgo",
]

MAX_RESULTS = 10
REQUEST_TIMEOUT = 25

# Avoid aggressive repeated requests.
MAX_RETRIES = 1
QUERY_COOLDOWN = 8

REGION = "in-en"

REPORT_FILE = "ddgs_diagnostic_results.json"

# ============================================================
# SEARCH TEST CASES
# ============================================================

SEARCH_TESTS = [

    # ---- General movie discovery ----

    {
        "id": "Q1",
        "category": "Broad Movie Search",
        "query": "Dangal 2016 movie review",
        "expected_domain": None,
    },

    {
        "id": "Q2",
        "category": "Exact Movie Search",
        "query": '"Dangal" 2016 movie review',
        "expected_domain": None,
    },

    # ---- Publisher-specific searches ----

    {
        "id": "Q3",
        "category": "Times of India",
        "query": (
            '"Dangal" movie review '
            "site:timesofindia.indiatimes.com"
        ),
        "expected_domain": "timesofindia.indiatimes.com",
    },

    {
        "id": "Q4",
        "category": "Hindustan Times",
        "query": (
            '"Dangal" movie review '
            "site:hindustantimes.com"
        ),
        "expected_domain": "hindustantimes.com",
    },

    {
        "id": "Q5",
        "category": "Filmfare",
        "query": (
            '"Dangal" movie review '
            "site:filmfare.com"
        ),
        "expected_domain": "filmfare.com",
    },

    {
        "id": "Q6",
        "category": "Bollywood Hungama",
        "query": (
            '"Dangal" movie review '
            "site:bollywoodhungama.com"
        ),
        "expected_domain": "bollywoodhungama.com",
    },

    # ---- Target movie discovery ----

    {
        "id": "Q7",
        "category": "Target Movie Broad",
        "query": (
            '"Bhai Tera Star Hai" '
            "2026 movie review"
        ),
        "expected_domain": None,
    },

    {
        "id": "Q8",
        "category": "Target Movie Times of India",
        "query": (
            '"Bhai Tera Star Hai" review '
            "site:timesofindia.indiatimes.com"
        ),
        "expected_domain": "timesofindia.indiatimes.com",
    },

    {
        "id": "Q9",
        "category": "Target Movie Bollywood Hungama",
        "query": (
            '"Bhai Tera Star Hai" review '
            "site:bollywoodhungama.com"
        ),
        "expected_domain": "bollywoodhungama.com",
    },

    # ---- Another Hindi film ----

    {
        "id": "Q10",
        "category": "Another Movie Publisher Search",
        "query": (
            '"3 Idiots" movie review '
            "site:hindustantimes.com"
        ),
        "expected_domain": "hindustantimes.com",
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

logger = logging.getLogger("ddgs-test")


def separator(char="=", width=90):
    print(char * width, flush=True)


# ============================================================
# URL VALIDATION
# ============================================================

def normalize_domain(url):
    try:
        hostname = urlparse(url).hostname or ""
        return hostname.lower().removeprefix("www.")
    except Exception:
        return ""


def domain_matches(url, expected_domain):

    if not expected_domain:
        return None

    actual = normalize_domain(url)
    expected = expected_domain.lower().removeprefix("www.")

    return (
        actual == expected
        or actual.endswith("." + expected)
    )


# ============================================================
# RESULT QUALITY
# ============================================================

def check_result_quality(result, expected_domain):

    title = str(result.get("title") or "")
    url = str(result.get("href") or "")
    snippet = str(result.get("body") or "")

    domain_match = domain_matches(
        url,
        expected_domain
    )

    valid_url = (
        urlparse(url).scheme in ("http", "https")
        and bool(urlparse(url).hostname)
    )

    # Heuristic only. A long title may be legitimate.
    # This flags suspicious results for manual review.
    suspicious_title = (
        len(title) > 160
        or title.count("...") >= 3
    )

    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "domain_match": domain_match,
        "valid_url": valid_url,
        "suspicious_title": suspicious_title,
    }


# ============================================================
# SEARCH EXECUTION
# ============================================================

def execute_search(query, backend):

    started = time.perf_counter()
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        logger.info(
            "Backend=%s | Attempt=%d/%d",
            backend,
            attempt,
            MAX_RETRIES,
        )

        try:

            with DDGS(timeout=REQUEST_TIMEOUT) as client:

                results = list(
                    client.text(
                        query,
                        region=REGION,
                        max_results=MAX_RESULTS,
                        backend=backend,
                        safesearch="moderate",
                    )
                )

            elapsed = time.perf_counter() - started

            if results:

                return {
                    "status": "SUCCESS",
                    "results": results,
                    "elapsed": elapsed,
                    "attempts": attempt,
                    "error": None,
                }

            last_error = "No results returned"

        except Exception as exc:

            last_error = (
                f"{type(exc).__name__}: {exc}"
            )

            logger.error(
                "Search failed: %s",
                last_error
            )

            traceback.print_exc(file=sys.stdout)

        if attempt < MAX_RETRIES:

            delay = 15 * attempt

            logger.info(
                "Retry cooldown: %d seconds",
                delay
            )

            time.sleep(delay)

    return {
        "status": (
            "ERROR" if last_error != "No results returned"
            else "EMPTY"
        ),
        "results": [],
        "elapsed": time.perf_counter() - started,
        "attempts": MAX_RETRIES,
        "error": last_error,
    }


# ============================================================
# PRINT INDIVIDUAL SEARCH
# ============================================================

def print_results(test, outcome):

    expected_domain = test["expected_domain"]

    print("\nRESULT STATUS:", outcome["status"])
    print("RESULT COUNT :", len(outcome["results"]))
    print("TIME         :", f"{outcome['elapsed']:.2f}s")

    if outcome["error"]:
        print("ERROR        :", outcome["error"])

    validated_results = []

    for index, result in enumerate(
        outcome["results"][:MAX_RESULTS],
        start=1,
    ):

        item = check_result_quality(
            result,
            expected_domain
        )

        validated_results.append(item)

        print()
        separator("-")

        print(f"RESULT {index}")

        print("TITLE   :", item["title"])
        print("URL     :", item["url"])
        print("SNIPPET :", item["snippet"])

        if expected_domain:

            print(
                "DOMAIN MATCH:",
                "YES" if item["domain_match"] else "NO"
            )

        print(
            "VALID URL:",
            "YES" if item["valid_url"] else "NO"
        )

        print(
            "SUSPICIOUS TITLE:",
            "YES" if item["suspicious_title"] else "NO"
        )

    matching = sum(
        item["domain_match"] is True
        for item in validated_results
    )

    valid_urls = sum(
        item["valid_url"]
        for item in validated_results
    )

    suspicious = sum(
        item["suspicious_title"]
        for item in validated_results
    )

    print()
    separator("-")

    print("SEARCH QUALITY SUMMARY")
    print("Total Results       :", len(validated_results))
    print("Valid URLs          :", valid_urls)
    print("Matching Publisher  :", matching)
    print("Suspicious Titles   :", suspicious)

    return {
        "matching_domains": matching,
        "valid_urls": valid_urls,
        "suspicious_titles": suspicious,
        "results": validated_results,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    separator()

    print("DDGS MOVIE REVIEW SEARCH DIAGNOSTIC")

    separator()

    print(
        "UTC:",
        datetime.now(timezone.utc).isoformat()
    )

    print("DDGS VERSION:", version("ddgs"))
    print("REGION:", REGION)
    print("MAX RESULTS:", MAX_RESULTS)
    print("COOLDOWN:", QUERY_COOLDOWN)

    print("\nBACKENDS:", ", ".join(BACKENDS))
    print("QUERIES PER BACKEND:", len(SEARCH_TESTS))

    total_tests = len(BACKENDS) * len(SEARCH_TESTS)

    print("TOTAL TESTS:", total_tests)

    summary = []
    detailed_report = []

    test_number = 0

    for backend in BACKENDS:

        print()
        separator("#")

        print("TESTING BACKEND:", backend.upper())

        separator("#")

        for test in SEARCH_TESTS:

            test_number += 1

            print()
            separator("=")

            print(
                f"TEST {test_number}/{total_tests}"
            )

            print("BACKEND :", backend)
            print("TYPE    :", test["category"])
            print("QUERY   :", test["query"])

            if test["expected_domain"]:
                print(
                    "EXPECTED:",
                    test["expected_domain"]
                )

            separator("=")

            outcome = execute_search(
                test["query"],
                backend
            )

            quality = print_results(
                test,
                outcome
            )

            record = {
                "backend": backend,
                "query_id": test["id"],
                "category": test["category"],
                "query": test["query"],
                "expected_domain": test["expected_domain"],
                "status": outcome["status"],
                "result_count": len(outcome["results"]),
                "elapsed": outcome["elapsed"],
                "attempts": outcome["attempts"],
                "error": outcome["error"],
                **quality,
            }

            summary.append(record)
            detailed_report.append(record)

            if test_number < total_tests:

                logger.info(
                    "Cooldown: %d seconds",
                    QUERY_COOLDOWN
                )

                time.sleep(QUERY_COOLDOWN)

    # ========================================================
    # FINAL BACKEND COMPARISON
    # ========================================================

    print()
    separator("=")

    print("FINAL BACKEND COMPARISON")

    separator("=")

    print(
        f"{'BACKEND':<15}"
        f"{'SUCCESS':<10}"
        f"{'ERRORS':<10}"
        f"{'RESULTS':<10}"
        f"{'DOMAIN HIT':<12}"
        f"{'AVG TIME':<10}"
    )

    separator("-")

    for backend in BACKENDS:

        records = [
            r for r in summary
            if r["backend"] == backend
        ]

        success = sum(
            r["status"] == "SUCCESS"
            for r in records
        )

        errors = sum(
            r["status"] == "ERROR"
            for r in records
        )

        results = sum(
            r["result_count"]
            for r in records
        )

        domain_hits = sum(
            r["matching_domains"]
            for r in records
        )

        avg_time = sum(
            r["elapsed"]
            for r in records
        ) / len(records)

        print(
            f"{backend:<15}"
            f"{success:<10}"
            f"{errors:<10}"
            f"{results:<10}"
            f"{domain_hits:<12}"
            f"{avg_time:<10.2f}"
        )

    separator("=")

    print("\nPUBLISHER-SPECIFIC QUERY PERFORMANCE")

    for backend in BACKENDS:

        records = [
            r for r in summary
            if r["backend"] == backend
            and r["expected_domain"]
        ]

        total_queries = len(records)

        with_matches = sum(
            r["matching_domains"] > 0
            for r in records
        )

        print(
            f"{backend:<15}"
            f"{with_matches}/{total_queries} queries "
            "returned matching publisher URLs"
        )

    # ========================================================
    # WRITE JSON REPORT
    # ========================================================

    with open(
        REPORT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            {
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
                "ddgs_version": version("ddgs"),
                "total_tests": total_tests,
                "results": detailed_report,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print()
    print("JSON REPORT SAVED:", REPORT_FILE)

    # Diagnostic job succeeds if at least one
    # publisher-specific query returned a matching URL.

    any_publisher_match = any(
        r["matching_domains"] > 0
        for r in summary
        if r["expected_domain"]
    )

    if not any_publisher_match:

        logger.error(
            "No publisher-specific searches succeeded."
        )

        return 1

    logger.info(
        "Diagnostic completed. Publisher URLs discovered."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
