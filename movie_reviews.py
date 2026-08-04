#!/usr/bin/env python3
"""
Fetch the first DuckDuckGo result title for a movie review, restricted to each
publisher's own domain using the site: operator.

Query built per publisher:   site:<domain> "<movie>" review

Output: a JSON object printed to STDOUT (all progress logs go to STDERR, so the
JSON on stdout stays clean and pipe-able, e.g. `python movie_reviews.py > out.json`).

--------------------------------------------------------------------------------
IMPORTANT (read before running in CI)
--------------------------------------------------------------------------------
DuckDuckGo aggressively rate-limits and often outright BLOCKS cloud IP ranges,
which includes GitHub-hosted Actions runners (Azure IPs). If every publisher
comes back with "found": false in CI, that is almost always the IP being
blocked -- NOT a bug in this script. It usually works fine from a normal
residential IP / your laptop.

Mitigations built in:
  * retries with exponential backoff        (MAX_RETRIES / RETRY_BACKOFF_SEC)
  * randomized delays between publishers     (MIN_DELAY_SEC / MAX_DELAY_SEC)
  * optional proxy via the DDGS_PROXY env var (recommended for reliable CI)

To use a proxy in CI, set a repository secret and expose it as DDGS_PROXY, e.g.
  export DDGS_PROXY="http://user:pass@host:port"    # http/https/socks5 supported
Or run the workflow on a self-hosted runner that isn't on a blocked cloud IP.
"""

import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# Package was renamed from `duckduckgo-search` to `ddgs`. Import the new name,
# fall back to the old one so this works whichever is installed.
try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    from duckduckgo_search import DDGS


# --------------------------------------------------------------------------- #
# CONFIG  --  edit these
# --------------------------------------------------------------------------- #

# The movie to search for. Can be overridden at runtime with the MOVIE_NAME
# environment variable (the GitHub Actions workflow wires this up for you).
DEFAULT_MOVIE_NAME = "Bhai tera star hai"

# Where the publisher list lives (same folder as this script by default).
PUBLISHERS_FILE = Path(__file__).parent / "publishers.json"

# Search behaviour
REGION = "in-en"          # India / English results
SAFESEARCH = "off"        # "off" | "moderate" | "on"
REQUEST_TIMEOUT = 20      # seconds per HTTP request

# Anti-rate-limit / politeness
MIN_DELAY_SEC = 2.0       # min pause between publishers
MAX_DELAY_SEC = 5.0       # max pause between publishers
MAX_RETRIES = 3           # attempts per publisher on empty/error
RETRY_BACKOFF_SEC = 8.0   # base backoff; multiplied by the attempt number

# Domain handling
STRIP_WWW = False         # True -> site:thehindu.com instead of site:www.thehindu.com
                          # (broadens matching to apex + subdomains; may add noise)

# Optional proxy (http/https/socks5). Read from env so secrets stay out of code.
PROXY = os.environ.get("DDGS_PROXY") or None


# --------------------------------------------------------------------------- #
# HELPERS
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    """Progress logging -> stderr, keeping stdout clean for the JSON payload."""
    print(msg, file=sys.stderr, flush=True)


def domain_from_url(url: str) -> str:
    """Return the host portion of a URL, e.g. 'www.example.com'."""
    netloc = urlparse(url).netloc
    if not netloc:  # url given without a scheme
        netloc = url.replace("https://", "").replace("http://", "").split("/")[0]
    if STRIP_WWW and netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def build_query(domain: str, movie: str) -> str:
    """site:<domain> "<movie>" review"""
    return f'site:{domain} "{movie}" review'


def _make_ddgs():
    """Create a DDGS instance, tolerating constructor differences between versions."""
    kwargs = {"timeout": REQUEST_TIMEOUT}
    if PROXY:
        kwargs["proxy"] = PROXY
    try:
        return DDGS(**kwargs)
    except TypeError:
        try:
            return DDGS(proxy=PROXY) if PROXY else DDGS()
        except TypeError:
            return DDGS()


def _text_search(ddgs, query):
    """Run a text search, tolerating signature differences between versions."""
    try:
        return list(ddgs.text(
            query, region=REGION, safesearch=SAFESEARCH, max_results=1))
    except (TypeError, ValueError):
        # Older/newer builds may reject region/safesearch or their values.
        return list(ddgs.text(query, max_results=1))


def first_result(query: str):
    """
    Return the first search-result dict for `query`, or None.
    Retries with backoff because CI IPs are frequently rate-limited.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with _make_ddgs() as ddgs:
                results = _text_search(ddgs, query)
            if results:
                return results[0]
        except Exception as exc:  # network / rate-limit / parse errors
            log(f"    ! attempt {attempt} error: {exc}")

        if attempt < MAX_RETRIES:
            sleep_for = RETRY_BACKOFF_SEC * attempt + random.uniform(0, 2)
            log(f"    ...empty/failed, backing off {sleep_for:.1f}s")
            time.sleep(sleep_for)

    return None


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #

def main() -> int:
    movie = (os.environ.get("MOVIE_NAME") or DEFAULT_MOVIE_NAME).strip()
    if not movie:
        movie = DEFAULT_MOVIE_NAME

    if not PUBLISHERS_FILE.exists():
        log(f"ERROR: publishers file not found at {PUBLISHERS_FILE}")
        return 1

    publishers = json.loads(PUBLISHERS_FILE.read_text(encoding="utf-8"))
    publishers = [p for p in publishers if p.get("active", True)]

    log(f"Movie: {movie!r}")
    log(f"Publishers: {len(publishers)}"
        + (f"  (proxy: on)" if PROXY else "  (proxy: off)"))
    log("")

    results = []
    for i, pub in enumerate(publishers, 1):
        name = pub["name"]
        domain = domain_from_url(pub["url"])
        query = build_query(domain, movie)

        log(f"[{i}/{len(publishers)}] {name}")
        log(f"    query: {query}")

        top = first_result(query)
        if top:
            title = (top.get("title") or "").strip()
            url = (top.get("href") or top.get("url") or "").strip()
            found = True
        else:
            title, url, found = None, None, False

        results.append({
            "publisher": name,
            "domain": domain,
            "title": title,
            "url": url,
            "found": found,
        })

        log(f"    -> {title if found else 'NO RESULT'}")

        if i < len(publishers):  # polite pause, skip after the last one
            time.sleep(random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC))

    payload = {
        "movie": movie,
        "publisher_count": len(publishers),
        "found_count": sum(1 for r in results if r["found"]),
        "results": results,
    }

    # The clean JSON payload -> stdout.
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
