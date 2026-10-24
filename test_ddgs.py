
#!/usr/bin/env python3
"""
YAHOO DDGS SEARCH DIAGNOSTIC
Compatible with DDGS 9.16.1 and Python 3.12.

Tests:
- Broad movie searches
- Exact-title searches
- Filmfare searches with multiple query formats
- Publisher-specific searches
- Known Hindi movie reviews

Features:
- Yahoo backend only
- Up to 10 results per search
- 3 attempts per query
- Retry delays: 15 seconds, 45 seconds
- Normal cooldown: 8 seconds
- Full results printed to GitHub Actions logs
- Publisher URL validation
- Suspicious title detection
- JSON report
"""

import json
import logging
import sys
import time
import traceback

from datetime import datetime, timezone
from importlib.metadata import version
from urllib.parse import urlparse

from ddgs import DDGS


# ============================================================
# CONFIGURATION
# ============================================================

BACKEND = "yahoo"
REGION = "in-en"
SAFESEARCH = "moderate"

MAX_RESULTS = 10
REQUEST_TIMEOUT = 25

MAX_ATTEMPTS = 3
RETRY_DELAYS = [15, 45]

NORMAL_COOLDOWN = 8

REPORT_FILE = "yahoo_ddgs_report.json"


# ============================================================
# TEST SCENARIOS
# ============================================================

TESTS = [
    {
        "id": "F1",
        "type": "Filmfare - Previously Failed Query",
        "query": '"Dangal" movie review site:filmfare.com',
        "expected_domain": "filmfare.com",
    },
    {
        "id": "F2",
        "type": "Filmfare - Unquoted Title",
        "query": "Dangal movie review site:filmfare.com",
        "expected_domain": "filmfare.com",
    },
    {
        "id": "F3",
        "type": "Filmfare - No Site Operator",
        "query": '"Dangal" movie review Filmfare',
        "expected_domain": "filmfare.com",
    },
    {
        "id": "F4",
        "type": "Filmfare - Exact Title and Year",
        "query": '"Dangal" 2016 review site:filmfare.com',
        "expected_domain": "filmfare.com",
    },
    {
        "id": "B1",
        "type": "Broad Movie Search",
        "query": "Dangal 2016 movie review",
        "expected_domain": None,
    },
    {
        "id": "B2",
        "type": "Broad Exact-Title Search",
        "query": '"Dangal" 2016 movie review',
        "expected_domain": None,
    },
    {
        "id": "H1",
        "type": "Hindustan Times - Site Operator",
        "query": '"Dangal" movie review site:hindustantimes.com',
        "expected_domain": "hindustantimes.com",
    },
    {
        "id": "H2",
        "type": "Hindustan Times - Publisher Name",
        "query": '"Dangal" movie review Hindustan Times',
        "expected_domain": "hindustantimes.com",
    },
    {
        "id": "T1",
        "type": "Target Movie - Broad",
        "query": '"Bhai Tera Star Hai" 2026 movie review',
        "expected_domain": None,
    },
    {
        "id": "T2",
        "type": "Target Movie - Times of India",
        "query": (
            '"Bhai Tera Star Hai" review '
            "site:timesofindia.indiatimes.com"
        ),
        "expected_domain": "timesofindia.indiatimes.com",
    },
    {
        "id": "T3",
        "type": "Target Movie - Bollywood Hungama",
        "query": (
            '"Bhai Tera Star Hai" review '
            "site:bollywoodhungama.com"
        ),
        "expected_domain": "bollywoodhungama.com",
    },
    {
        "id": "I1",
        "type": "Another Film - Hindustan Times",
        "query": '"3 Idiots" movie review site:hindustantimes.com',
        "expected_domain": "hindustantimes.com",
    },
]


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s "
        "[%(levelname)s] %(message)s"
    ),
    stream=sys.stdout,
    force=True,
)

logger = logging.getLogger("yahoo-ddgs")


def separator(character="=", width=90):
    print(character * width, flush=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# DOMAIN CHECKING
# ============================================================

def get_domain(url):
    try:
        return (
            urlparse(url)
            .hostname
            or ""
        ).lower().removeprefix("www.")
    except Exception:
        return ""


def is_valid_url(url):
    try:
        parsed = urlparse(url)

        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
        )
    except Exception:
        return False


def matches_domain(url, expected_domain):
    if not expected_domain:
        return None

    actual = get_domain(url)

    expected = (
        expected_domain
        .lower()
        .removeprefix("www.")
    )

    return (
        actual == expected
        or actual.endswith("." + expected)
    )


# ============================================================
# RESULT QUALITY CHECK
# ============================================================

def analyze_result(result, expected_domain):

    title = str(result.get("title") or "")
    url = str(
        result.get("href")
        or result.get("url")
        or ""
    )
    snippet = str(result.get("body") or "")

    suspicious_title = (
        len(title) > 160
        or title.count("...") >= 3
    )

    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "domain": get_domain(url),
        "valid_url": is_valid_url(url),
        "domain_match": matches_domain(
            url,
            expected_domain
        ),
        "suspicious_title": suspicious_title,
    }


# ============================================================
# SEARCH WITH COOLDOWN AND RETRY
# ============================================================

def search_yahoo(query):

    overall_start = time.perf_counter()

    attempt_history = []
    last_error = None
    last_status = "ERROR"

    for attempt in range(1, MAX_ATTEMPTS + 1):

        separator("-")

        logger.info(
            "SEARCH ATTEMPT %d/%d",
            attempt,
            MAX_ATTEMPTS,
        )

        logger.info("Backend: %s", BACKEND)
        logger.info("Query: %s", query)

        attempt_start = time.perf_counter()

        try:

            # Fresh client on every attempt.
            with DDGS(
                timeout=REQUEST_TIMEOUT
            ) as client:

                results = list(
                    client.text(
                        query,
                        backend=BACKEND,
                        region=REGION,
                        safesearch=SAFESEARCH,
                        max_results=MAX_RESULTS,
                    )
                )

            elapsed = (
                time.perf_counter() - attempt_start
            )

            if results:

                logger.info(
                    "SUCCESS: %d results in %.2fs",
                    len(results),
                    elapsed,
                )

                attempt_history.append({
                    "attempt": attempt,
                    "status": "SUCCESS",
                    "results": len(results),
                    "elapsed": round(elapsed, 3),
                    "error": None,
                })

                return {
                    "status": "SUCCESS",
                    "results": results,
                    "attempts": attempt,
                    "attempt_history": attempt_history,
                    "elapsed": round(
                        time.perf_counter()
                        - overall_start,
                        3,
                    ),
                    "error": None,
                }

            last_status = "EMPTY"
            last_error = "Empty result list"

            logger.warning(
                "EMPTY RESPONSE: no results returned."
            )

            attempt_history.append({
                "attempt": attempt,
                "status": "EMPTY",
                "results": 0,
                "elapsed": round(elapsed, 3),
                "error": last_error,
            })

        except Exception as exc:

            elapsed = (
                time.perf_counter() - attempt_start
            )

            last_status = "ERROR"

            last_error = (
                f"{type(exc).__name__}: {exc}"
            )

            logger.error(
                "SEARCH FAILURE: %s",
                last_error,
            )

            traceback.print_exc(file=sys.stdout)

            attempt_history.append({
                "attempt": attempt,
                "status": "ERROR",
                "results": 0,
                "elapsed": round(elapsed, 3),
                "error": last_error,
            })

        # Retry even when the exception says
        # "No results found".
        if attempt < MAX_ATTEMPTS:

            cooldown = RETRY_DELAYS[attempt - 1]

            logger.warning(
                "Attempt %d failed. "
                "Cooling down %d seconds "
                "before retry.",
                attempt,
                cooldown,
            )

            time.sleep(cooldown)

    return {
        "status": last_status,
        "results": [],
        "attempts": MAX_ATTEMPTS,
        "attempt_history": attempt_history,
        "elapsed": round(
            time.perf_counter() - overall_start,
            3,
        ),
        "error": last_error,
    }


# ============================================================
# PRINT SEARCH RESULTS
# ============================================================

def print_search_results(test, outcome):

    expected_domain = test["expected_domain"]

    print()
    separator("-")

    print("FINAL SEARCH STATUS :", outcome["status"])
    print("ATTEMPTS            :", outcome["attempts"])
    print("RESULT COUNT        :", len(outcome["results"]))
    print("TOTAL ELAPSED       :", outcome["elapsed"])

    if outcome["error"]:
        print("LAST ERROR          :", outcome["error"])

    print()
    print("ATTEMPT HISTORY")

    for item in outcome["attempt_history"]:

        print(
            "Attempt {attempt}: "
            "{status}, "
            "{results} results, "
            "{elapsed}s".format(**item)
        )

        if item["error"]:
            print("  Error:", item["error"])

    analyzed_results = []

    for index, raw_result in enumerate(
        outcome["results"],
        start=1,
    ):

        item = analyze_result(
            raw_result,
            expected_domain,
        )

        analyzed_results.append(item)

        print()
        separator("-")

        print("RESULT", index)
        print("TITLE   :", item["title"])
        print("URL     :", item["url"])
        print("DOMAIN  :", item["domain"])
        print("SNIPPET :", item["snippet"])

        print(
            "VALID URL:",
            "YES" if item["valid_url"] else "NO"
        )

        if expected_domain:

            print(
                "DOMAIN MATCH:",
                "YES" if item["domain_match"] else "NO"
            )

        print(
            "SUSPICIOUS TITLE:",
            "YES" if item["suspicious_title"] else "NO"
        )

    matching_results = sum(
        item["domain_match"] is True
        for item in analyzed_results
    )

    valid_results = sum(
        item["valid_url"]
        for item in analyzed_results
    )

    suspicious_results = sum(
        item["suspicious_title"]
        for item in analyzed_results
    )

    # A successful response may have no results
    # belonging to the requested publisher.
    publisher_found = (
        matching_results > 0
        if expected_domain
        else None
    )

    print()
    separator("-")

    print("SEARCH QUALITY SUMMARY")
    print("Total Results      :", len(analyzed_results))
    print("Valid URLs         :", valid_results)
    print("Publisher Matches  :", matching_results)
    print("Suspicious Titles  :", suspicious_results)

    if expected_domain:

        print(
            "Publisher Found    :",
            "YES" if publisher_found else "NO"
        )

    return {
        "results": analyzed_results,
        "valid_urls": valid_results,
        "publisher_matches": matching_results,
        "publisher_found": publisher_found,
        "suspicious_titles": suspicious_results,
    }


# ============================================================
# FINAL REPORT
# ============================================================

def print_final_summary(records):

    print()
    separator("=")

    print("FINAL YAHOO DDGS DIAGNOSTIC SUMMARY")

    separator("=")

    header = (
        f"{'ID':<5}"
        f"{'STATUS':<10}"
        f"{'TRY':<6}"
        f"{'RESULTS':<9}"
        f"{'MATCHES':<10}"
        f"{'TIME':<10}"
    )

    print(header)
    separator("-")

    for record in records:

        print(
            f"{record['id']:<5}"
            f"{record['status']:<10}"
            f"{record['attempts']:<6}"
            f"{record['result_count']:<9}"
            f"{record['publisher_matches']:<10}"
            f"{record['elapsed']:<10.2f}"
        )

    separator("=")

    total = len(records)

    successful = sum(
        record["status"] == "SUCCESS"
        for record in records
    )

    errors = sum(
        record["status"] == "ERROR"
        for record in records
    )

    empty = sum(
        record["status"] == "EMPTY"
        for record in records
    )

    recovered = sum(
        record["status"] == "SUCCESS"
        and record["attempts"] > 1
        for record in records
    )

    total_results = sum(
        record["result_count"]
        for record in records
    )

    suspicious = sum(
        record["suspicious_titles"]
        for record in records
    )

    publisher_tests = [
        record
        for record in records
        if record["expected_domain"]
    ]

    publisher_hits = sum(
        record["publisher_found"] is True
        for record in publisher_tests
    )

    print()
    print("TOTAL QUERIES          :", total)
    print("SUCCESSFUL QUERIES     :", successful)
    print("FAILED QUERIES         :", errors)
    print("EMPTY QUERIES          :", empty)
    print("RECOVERED AFTER RETRY  :", recovered)
    print("TOTAL RESULTS          :", total_results)
    print("SUSPICIOUS TITLES      :", suspicious)

    print(
        "PUBLISHER QUERIES FOUND:",
        f"{publisher_hits}/{len(publisher_tests)}"
    )

    print(
        "SEARCH SUCCESS RATE    :",
        f"{successful / total * 100:.1f}%"
        if total else "N/A"
    )

    print()
    separator("=")

    print("FILMFARE SCENARIO COMPARISON")

    separator("=")

    for record in records:

        if record["id"].startswith("F"):

            print()
            print("TEST:", record["id"])
            print("QUERY:", record["query"])
            print("STATUS:", record["status"])
            print("ATTEMPTS:", record["attempts"])
            print(
                "FILMFARE URL FOUND:",
                "YES" if record["publisher_found"] else "NO"
            )
            print(
                "MATCHING URLS:",
                record["publisher_matches"]
            )

    print()
    separator("=")


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    separator("=")

    print("YAHOO DDGS MOVIE REVIEW DIAGNOSTIC")

    separator("=")

    print("UTC TIME         :", utc_now())
    print("PYTHON VERSION   :", sys.version.split()[0])
    print("DDGS VERSION     :", version("ddgs"))
    print("BACKEND          :", BACKEND)
    print("REGION           :", REGION)
    print("MAX RESULTS      :", MAX_RESULTS)
    print("MAX ATTEMPTS     :", MAX_ATTEMPTS)
    print("RETRY DELAYS     :", RETRY_DELAYS)
    print("NORMAL COOLDOWN  :", NORMAL_COOLDOWN)
    print("TOTAL TESTS      :", len(TESTS))

    separator("=")

    records = []

    for number, test in enumerate(TESTS, start=1):

        print()
        separator("#")

        print(f"TEST {number}/{len(TESTS)}")
        print("TEST ID :", test["id"])
        print("TYPE    :", test["type"])
        print("QUERY   :", test["query"])

        if test["expected_domain"]:
            print(
                "EXPECTED DOMAIN:",
                test["expected_domain"]
            )

        separator("#")

        outcome = search_yahoo(
            test["query"]
        )

        quality = print_search_results(
            test,
            outcome
        )

        record = {
            "id": test["id"],
            "type": test["type"],
            "query": test["query"],
            "expected_domain": test["expected_domain"],
            "status": outcome["status"],
            "result_count": len(outcome["results"]),
            "attempts": outcome["attempts"],
            "attempt_history": outcome["attempt_history"],
            "elapsed": outcome["elapsed"],
            "error": outcome["error"],
            **quality,
        }

        records.append(record)

        # Save after each query so partial results
        # survive an interrupted diagnostic run.
        with open(
            REPORT_FILE,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                {
                    "timestamp": utc_now(),
                    "backend": BACKEND,
                    "ddgs_version": version("ddgs"),
                    "results": records,
                },
                file,
                indent=2,
                ensure_ascii=False,
            )

        if number < len(TESTS):

            logger.info(
                "Normal cooldown: %d seconds",
                NORMAL_COOLDOWN,
            )

            time.sleep(NORMAL_COOLDOWN)

    print_final_summary(records)

    print()
    logger.info(
        "JSON report saved: %s",
        REPORT_FILE,
    )

    if not any(
        record["publisher_found"] is True
        for record in records
    ):

        logger.error(
            "No publisher-specific URL discovered."
        )

        return 1

    logger.info(
        "Diagnostic completed."
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
