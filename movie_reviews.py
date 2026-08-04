#!/usr/bin/env python3
"""
Single-publisher test: HINDUSTAN TIMES only.

Purpose: get one publisher working and, if it fails, tell us *why* (the full
error + your environment) instead of a vague "builder error".

Run:
    python test_hindustan_times.py
    MOVIE_NAME="Chhaava" python test_hindustan_times.py     # try a real movie

What it does, in order:
  1. Prints proxy env vars + versions (diagnostics).
  2. Removes malformed proxy env vars -> the usual cause of BuilderError.
  3. Tries the search via ddgs.
  4. If ddgs still fails, falls back to a plain-requests DuckDuckGo scrape
     (bypasses ddgs's Rust HTTP client entirely).
"""

import os
import re
import sys
import json
import html as _html

MOVIE = (os.environ.get("MOVIE_NAME") or "Bhai tera star hai").strip()
PUBLISHER = "Hindustan Times"
DOMAIN = "www.hindustantimes.com"
QUERY = f'site:{DOMAIN} "{MOVIE}" review'

PROXY_VARS = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy"]


def diagnostics_and_cleanup():
    print("=== proxy environment ===")
    any_proxy = False
    for v in PROXY_VARS:
        val = os.environ.get(v)
        if val:
            any_proxy = True
            print(f"  {v} = {val!r}")
    if not any_proxy:
        print("  (none set)")

    # Strip malformed proxies (value without a '://' scheme) -> BuilderError source.
    for v in PROXY_VARS:
        val = os.environ.get(v)
        if val and "://" not in val:
            print(f"  -> removing malformed {v} (missing scheme like http://)")
            os.environ.pop(v, None)

    print("\n=== versions ===")
    print("python:", sys.version.split()[0])
    try:
        import ddgs
        print("ddgs  :", getattr(ddgs, "__version__", "unknown"))
    except Exception as e:
        print("ddgs  : IMPORT FAILED ->", e)
    try:
        import primp
        print("primp :", getattr(primp, "__version__", "unknown"))
    except Exception:
        print("primp : (bundled / not directly importable)")

    print(f"\n=== query ===\n{QUERY}\n")


def via_ddgs():
    from ddgs import DDGS
    with DDGS(timeout=20) as d:
        res = list(d.text(QUERY, region="in-en", safesearch="off", max_results=1))
    if res:
        top = res[0]
        return top.get("title"), (top.get("href") or top.get("url"))
    return None, None


def via_requests():
    """primp-free fallback: scrape DuckDuckGo's HTML endpoint with requests."""
    import requests
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    r = requests.post("https://html.duckduckgo.com/html/",
                      data={"q": QUERY},
                      headers={"User-Agent": ua},
                      timeout=20)
    if any(w in r.text.lower() for w in ("anomaly", "blocked", "captcha")):
        raise RuntimeError(f"DuckDuckGo returned a block page (HTTP {r.status_code}) "
                           f"- this IP is rate-limited.")
    r.raise_for_status()
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', r.text, re.S)
    links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', r.text)
    if titles:
        title = _html.unescape(re.sub("<.*?>", "", titles[0])).strip()
        return title, (links[0] if links else None)
    return None, None


def main():
    diagnostics_and_cleanup()

    title = url = None
    for label, fn in [("ddgs", via_ddgs), ("requests fallback", via_requests)]:
        try:
            title, url = fn()
            print(f"[{label}] OK -> {'HIT' if title else 'no result (empty)'}")
            if title:
                break
        except Exception as e:
            print(f"[{label}] ERROR: {type(e).__name__}: {e}")

    print("\n=== RESULT ===")
    print(json.dumps({
        "publisher": PUBLISHER,
        "movie": MOVIE,
        "title": title,
        "url": url,
        "found": bool(title),
    }, ensure_ascii=False, indent=2))

    if not title:
        print("\nHow to read this:")
        print("  * 'builder error' above  -> a proxy/client-config problem in THIS")
        print("    environment. Check the proxy vars printed at the top.")
        print("  * a 'block page' / 202   -> DuckDuckGo is rate-limiting this IP")
        print("    (use a proxy or run from a different network).")


if __name__ == "__main__":
    main()
