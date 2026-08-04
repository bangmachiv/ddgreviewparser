#!/usr/bin/env python3
"""
Movie-review first-result finder  --  RCA / DIAGNOSTIC BUILD
============================================================

Same job as before (for each publisher, run  site:<domain> "<movie>" review
and grab the first result title), but instrumented with heavy logging so that
WHEN it fails you can see exactly WHY, not just `('builder error', None)`.

Run:
    python movie_reviews.py                      # all publishers
    LIMIT=1 python movie_reviews.py              # only the first publisher
    LIMIT=1 MOVIE_NAME="Chhaava" python movie_reviews.py

Console (stderr) gets the verbose diagnostics; the final JSON goes to stdout,
so this still works:  python movie_reviews.py > results.json

Layers of instrumentation
-------------------------
  PHASE 0  environment report .... python / ddgs / primp / requests / OS / proxy vars
  PHASE 1  proxy cleanup ......... clears proxy vars (the #1 cause of builder errors)
  PHASE 2  preflight probes ...... DNS + raw primp GET + raw requests GET to DuckDuckGo
                                    -> isolates "network/primp broken" from "ddgs broken"
  PHASE 3  per-publisher search .. ddgs(auto) -> per-backend probe -> requests fallback,
                                    with full tracebacks + timings on every failure
  PHASE 4  summary + RCA hints ... interprets the observations into a likely root cause
"""

import json
import os
import platform
import random
import socket
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# --------------------------------------------------------------------------- #
# CONFIG
# --------------------------------------------------------------------------- #
DEFAULT_MOVIE_NAME = "Bhai tera star hai"
PUBLISHERS_FILE = Path(__file__).parent / "publishers.json"

LIMIT = int(os.environ.get("LIMIT", "0"))        # 0 = all publishers
CLEAR_ALL_PROXIES = True                          # clear every proxy var before searching

REGION = "in-en"
SAFESEARCH = "off"
REQUEST_TIMEOUT = 20

MIN_DELAY_SEC = 2.0
MAX_DELAY_SEC = 4.0
MAX_RETRIES = 2                                   # per strategy
RETRY_BACKOFF_SEC = 6.0

# Text backends to probe individually when the default "auto" fails.
PROBE_BACKENDS = ["duckduckgo", "google", "bing", "brave", "mojeek", "yandex", "yahoo"]

PROXY_VARS = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "no_proxy"]

_START = time.monotonic()


# --------------------------------------------------------------------------- #
# LOGGING  (everything -> stderr; keeps stdout clean for the JSON payload)
# --------------------------------------------------------------------------- #
def log(level, msg=""):
    elapsed = time.monotonic() - _START
    print(f"[{elapsed:7.2f}s] {level:<5} {msg}", file=sys.stderr, flush=True)


def banner(title):
    log("")
    log("=" * 4, f"===== {title} " + "=" * (60 - len(title)))


def log_exc(prefix):
    """Log the full traceback of the exception currently being handled."""
    exc = sys.exc_info()[1]
    log("ERROR", f"{prefix}: {type(exc).__name__}: {exc!r}")
    for line in traceback.format_exc().rstrip().splitlines():
        log("DEBUG", "    " + line)


# --------------------------------------------------------------------------- #
# PHASE 0 - environment report
# --------------------------------------------------------------------------- #
def phase0_environment(movie, publishers_count):
    banner("PHASE 0  environment")
    log("INFO", f"utc time      : {datetime.now(timezone.utc).isoformat()}")
    log("INFO", f"python        : {sys.version.split()[0]}  ({platform.python_implementation()})")
    log("INFO", f"platform      : {platform.system()} {platform.release()} / {platform.machine()}")
    log("INFO", f"cwd           : {os.getcwd()}")
    log("INFO", f"script dir    : {Path(__file__).parent}")

    for mod in ("ddgs", "primp", "requests"):
        try:
            m = __import__(mod)
            log("INFO", f"{mod:<13} : {getattr(m, '__version__', 'unknown')}")
        except Exception as e:
            log("WARN", f"{mod:<13} : NOT AVAILABLE ({e})")

    banner("PHASE 0  proxy-related environment variables")
    seen = False
    for v in PROXY_VARS:
        if os.environ.get(v):
            seen = True
            log("INFO", f"{v} = {os.environ[v]!r}")
    if not seen:
        log("INFO", "(no proxy/no_proxy variables set)")

    log("INFO", f"config        : movie={movie!r}  publishers={publishers_count}  "
                f"limit={LIMIT or 'all'}  clear_all_proxies={CLEAR_ALL_PROXIES}")


# --------------------------------------------------------------------------- #
# PHASE 1 - proxy cleanup
# --------------------------------------------------------------------------- #
def phase1_proxy_cleanup():
    banner("PHASE 1  proxy cleanup")
    if not CLEAR_ALL_PROXIES:
        removed = []
        for v in PROXY_VARS:
            val = os.environ.get(v)
            if val and v.lower() != "no_proxy" and "://" not in val:
                os.environ.pop(v, None)
                removed.append(v)
        log("INFO", f"removed malformed-only: {removed or 'none'}")
        return
    removed = [v for v in PROXY_VARS if v.lower() not in ("no_proxy",)
               and os.environ.pop(v, None) is not None]
    log("INFO", f"cleared proxy vars: {removed or 'none'}")
    log("INFO", "-> a proxy can no longer be the cause of a builder error on this run")


# --------------------------------------------------------------------------- #
# PHASE 2 - preflight connectivity probes
# --------------------------------------------------------------------------- #
def phase2_preflight():
    banner("PHASE 2  preflight connectivity")
    findings = {}

    # 2a. DNS
    try:
        t = time.monotonic()
        ip = socket.gethostbyname("duckduckgo.com")
        log("OK", f"DNS duckduckgo.com -> {ip}  ({(time.monotonic()-t)*1000:.0f} ms)")
        findings["dns"] = True
    except Exception:
        log_exc("DNS resolution failed")
        findings["dns"] = False

    # 2b. raw primp GET (this is what ddgs uses under the hood)
    try:
        import primp
        t = time.monotonic()
        c = primp.Client(timeout=REQUEST_TIMEOUT)
        r = c.get("https://duckduckgo.com/")
        blocked = any(w in r.text.lower() for w in ("anomaly", "captcha", "unusual traffic"))
        log("OK" if not blocked else "WARN",
            f"primp GET duckduckgo -> HTTP {r.status_code}  len={len(r.text)}  "
            f"{'(BLOCK PAGE)' if blocked else 'ok'}  ({(time.monotonic()-t)*1000:.0f} ms)")
        findings["primp_get"] = ("blocked" if blocked else r.status_code)
    except Exception:
        log_exc("primp GET failed  <-- if this is a builder error, primp/proxy is the RCA")
        findings["primp_get"] = "error"

    # 2c. raw requests GET (primp-free path)
    try:
        import requests
        t = time.monotonic()
        r = requests.get("https://duckduckgo.com/", timeout=REQUEST_TIMEOUT,
                         headers={"User-Agent": "Mozilla/5.0"})
        blocked = any(w in r.text.lower() for w in ("anomaly", "captcha", "unusual traffic"))
        log("OK" if not blocked else "WARN",
            f"requests GET duckduckgo -> HTTP {r.status_code}  len={len(r.text)}  "
            f"{'(BLOCK PAGE)' if blocked else 'ok'}  ({(time.monotonic()-t)*1000:.0f} ms)")
        findings["requests_get"] = ("blocked" if blocked else r.status_code)
    except Exception:
        log_exc("requests GET failed")
        findings["requests_get"] = "error"

    return findings


# --------------------------------------------------------------------------- #
# search helpers
# --------------------------------------------------------------------------- #
def domain_from_url(url):
    netloc = urlparse(url).netloc
    if not netloc:
        netloc = url.replace("https://", "").replace("http://", "").split("/")[0]
    return netloc


def build_query(domain, movie):
    return f'site:{domain} "{movie}" review'


def _normalize(row):
    title = (row.get("title") or "").strip()
    url = (row.get("href") or row.get("url") or "").strip()
    return title, url


def ddgs_auto(query):
    """Strategy 1: ddgs default (auto backend), with retries + full logging."""
    from ddgs import DDGS
    for attempt in range(1, MAX_RETRIES + 1):
        t = time.monotonic()
        try:
            with DDGS(timeout=REQUEST_TIMEOUT) as d:
                rows = list(d.text(query, region=REGION, safesearch=SAFESEARCH, max_results=1))
            log("INFO", f"    ddgs(auto) attempt {attempt}: {len(rows)} row(s) "
                        f"({(time.monotonic()-t)*1000:.0f} ms)")
            if rows:
                return _normalize(rows[0])
        except Exception:
            log_exc(f"    ddgs(auto) attempt {attempt}")
        if attempt < MAX_RETRIES:
            back = RETRY_BACKOFF_SEC * attempt + random.uniform(0, 2)
            log("INFO", f"    backing off {back:.1f}s")
            time.sleep(back)
    return None, None


def ddgs_per_backend(query):
    """Strategy 2: probe each backend individually to localize the failure."""
    from ddgs import DDGS
    for be in PROBE_BACKENDS:
        t = time.monotonic()
        try:
            with DDGS(timeout=REQUEST_TIMEOUT) as d:
                rows = list(d.text(query, region=REGION, safesearch=SAFESEARCH,
                                   max_results=1, backend=be))
            status = f"{len(rows)} row(s)"
            log("OK" if rows else "INFO",
                f"    backend {be:<11}: {status}  ({(time.monotonic()-t)*1000:.0f} ms)")
            if rows:
                return be, _normalize(rows[0])
        except Exception:
            exc = sys.exc_info()[1]
            log("WARN", f"    backend {be:<11}: {type(exc).__name__}: {exc!r}")
        time.sleep(random.uniform(0.5, 1.2))
    return None, (None, None)


def requests_fallback(query):
    """Strategy 3: primp-free scrape of DuckDuckGo's HTML endpoint."""
    import re, html as _html, requests
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    t = time.monotonic()
    r = requests.post("https://html.duckduckgo.com/html/", data={"q": query},
                     headers={"User-Agent": ua}, timeout=REQUEST_TIMEOUT)
    ms = (time.monotonic() - t) * 1000
    if any(w in r.text.lower() for w in ("anomaly", "captcha", "unusual traffic")):
        log("WARN", f"    requests fallback: BLOCK PAGE (HTTP {r.status_code}, {ms:.0f} ms)")
        return None, None
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', r.text, re.S)
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', r.text)
    log("INFO", f"    requests fallback: HTTP {r.status_code}, {len(titles)} title(s) ({ms:.0f} ms)")
    if titles:
        title = _html.unescape(re.sub("<.*?>", "", titles[0])).strip()
        return title, (links[0] if links else "")
    return None, None


def search_one(name, domain, query):
    """Run all strategies for a single publisher; return (title, url, method)."""
    log("STEP", f"strategy 1: ddgs(auto)")
    title, url = ddgs_auto(query)
    if title:
        return title, url, "ddgs-auto"

    log("STEP", f"strategy 2: per-backend probe")
    be, (title, url) = ddgs_per_backend(query)
    if title:
        return title, url, f"ddgs-{be}"

    log("STEP", f"strategy 3: requests fallback")
    try:
        title, url = requests_fallback(query)
        if title:
            return title, url, "requests"
    except Exception:
        log_exc("    requests fallback")

    return None, None, None


# --------------------------------------------------------------------------- #
# PHASE 4 - RCA interpretation
# --------------------------------------------------------------------------- #
def phase4_rca(preflight, results):
    banner("PHASE 4  RCA hints")
    found = sum(1 for r in results if r["found"])
    log("INFO", f"publishers searched : {len(results)}   found : {found}")

    if found == len(results) and results:
        log("OK", "everything worked -- no failure to diagnose.")
        return

    dns = preflight.get("dns")
    primp_get = preflight.get("primp_get")
    req_get = preflight.get("requests_get")

    if dns is False:
        log("RCA", "DNS failed -> no network egress at all (firewall / offline). "
                   "Nothing DuckDuckGo-specific; fix connectivity first.")
    elif primp_get == "error":
        log("RCA", "raw primp GET errored while requests/DNS may be fine -> the fault is in "
                   "primp/ddgs's client itself (proxy var or a broken primp build), NOT the "
                   "query or DuckDuckGo. If a proxy var was printed in PHASE 0, that's it; "
                   "otherwise reinstall: pip install --force-reinstall --no-cache-dir primp ddgs")
    elif primp_get == "blocked" or req_get == "blocked":
        log("RCA", "DuckDuckGo returned a BLOCK/anomaly page -> this IP is rate-limited "
                   "(classic on GitHub-hosted runners). Use a proxy (DDGS_PROXY) or a "
                   "self-hosted / different-network runner.")
    else:
        log("RCA", "network + client look healthy but searches returned nothing. Most likely "
                   "the query genuinely has no results (try MOVIE_NAME=\"Chhaava\" to confirm the "
                   "pipeline), or specific backends are throttled -- see the per-backend lines above.")


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #
def main():
    movie = (os.environ.get("MOVIE_NAME") or DEFAULT_MOVIE_NAME).strip() or DEFAULT_MOVIE_NAME

    if not PUBLISHERS_FILE.exists():
        log("ERROR", f"publishers file not found: {PUBLISHERS_FILE}")
        return 1
    publishers = [p for p in json.loads(PUBLISHERS_FILE.read_text(encoding="utf-8"))
                  if p.get("active", True)]
    if LIMIT > 0:
        publishers = publishers[:LIMIT]

    phase0_environment(movie, len(publishers))
    phase1_proxy_cleanup()
    preflight = phase2_preflight()

    banner("PHASE 3  per-publisher search")
    results = []
    for i, pub in enumerate(publishers, 1):
        name = pub["name"]
        domain = domain_from_url(pub["url"])
        query = build_query(domain, movie)
        log("")
        log("STEP", f"[{i}/{len(publishers)}] {name}   domain={domain}")
        log("INFO", f"    query: {query}")

        t = time.monotonic()
        title, url, method = search_one(name, domain, query)
        log("OK" if title else "WARN",
            f"    => {'HIT via ' + method if title else 'NO RESULT'}  "
            f"(total {(time.monotonic()-t):.1f}s)")
        if title:
            log("INFO", f"    title: {title[:110]}")

        results.append({
            "publisher": name, "domain": domain, "title": title,
            "url": url, "method": method, "found": bool(title),
        })

        if i < len(publishers):
            time.sleep(random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC))

    phase4_rca(preflight, results)

    payload = {
        "movie": movie,
        "publisher_count": len(results),
        "found_count": sum(1 for r in results if r["found"]),
        "results": results,
    }
    banner("RESULT JSON (stdout)")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
