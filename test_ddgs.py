#!/usr/bin/env python3
"""
DDGS STAGED DIAGNOSTIC SUITE (SINGLE-FILE EDITION)

Modes:
  1. Orchestrator (default):
     Creates isolated venvs for each DDGS version (9.14.4, 9.15.0, 9.16.0, 9.16.1, latest),
     re-invokes this same file with --worker inside each venv, streams all logs live,
     and builds ranked CSV / Excel (.xlsx) / JSON reports.
  2. Worker (--worker):
     Runs inside an isolated venv. Dynamically discovers registered text backends,
     instruments BaseSearchEngine & HttpClient to capture real HTTP status codes,
     final URLs, applied headers, and markup signals, executes Stages 1-5, and
     writes incremental CSV/JSONL checkpoints.
  3. Merge-only (--merge-only DIR):
     Aggregates raw CSV/JSON outputs across Python 3.10 / 3.11 / 3.12 runs into one
     globally ranked CSV / Excel / JSON report.
"""

from __future__ import annotations

import argparse
import csv
import inspect
import json
import logging
import os
import platform
import re
import statistics
import subprocess
import sys
import threading
import time
import venv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Force immediate line-buffered log streaming (critical for GitHub Actions)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)


# ============================================================
# CONFIGURATION & SPEC MATRIX (SECTIONS 1-14)
# ============================================================

DEFAULT_DDGS_VERSIONS = ["9.14.4", "9.15.0", "9.16.0", "9.16.1", "latest"]

CANDIDATE_BACKENDS = [
    "auto",
    "duckduckgo",
    "yahoo",
    "brave",
    "mojeek",
    "startpage",
    "yandex",
    "google",
    "bing",
]

REGIONS: list[str | None] = [
    "in-en",
    "in",
    "wt-wt",
    "us-en",
    "uk-en",
    "au-en",
    "ca-en",
    None,  # library default
]

SAFESEARCH_VALUES = ["off", "moderate", "strict"]
MAX_RESULTS_VALUES = [5, 10, 20, 30, 50]
TIMEOUT_VALUES = [10, 20, 30, 45]
PAGE_VALUES = [1, 2, 3]

RETRY_PAIRS_FULL = [(1, 2), (2, 2), (2, 5), (3, 5), (3, 15)]
RETRY_PAIRS_QUICK = [(1, 2), (2, 5), (3, 15)]
COOLDOWN_VALUES = [0, 2, 5, 8]
CONCURRENCY_VALUES = [1, 2, 3]

HEADER_PROFILES: dict[str, dict[str, str] | None] = {
    "default": None,
    "browser_ua": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    },
    "accept_html": {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    "accept_language": {
        "Accept-Language": "en-IN,en;q=0.9",
    },
    "referer_homepage": {
        "__dynamic_referer__": "true",
    },
    "combined_browser": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "__dynamic_referer__": "true",
    },
}

BASELINE_MOVIE = {
    "movie": "Dangal",
    "year": "2016",
    "publisher": "Hindustan Times",
    "domain": "hindustantimes.com",
}

VALIDATION_CORPUS = [
    {"movie": "Dangal", "year": "2016", "publisher": "Hindustan Times", "domain": "hindustantimes.com"},
    {"movie": "Dangal", "year": "2016", "publisher": "Filmfare", "domain": "filmfare.com"},
    {"movie": "3 Idiots", "year": "2009", "publisher": "Hindustan Times", "domain": "hindustantimes.com"},
    {"movie": "Jawan", "year": "2023", "publisher": "Times of India", "domain": "timesofindia.indiatimes.com"},
    {"movie": "Jawan", "year": "2023", "publisher": "Bollywood Hungama", "domain": "bollywoodhungama.com"},
    {"movie": "Bhai Tera Star Hai", "year": "2026", "publisher": "Times of India", "domain": "timesofindia.indiatimes.com"},
    {"movie": "Bhai Tera Star Hai", "year": "2026", "publisher": "Bollywood Hungama", "domain": "bollywoodhungama.com"},
]

ANTIBOT_PATTERNS = re.compile(
    r"(captcha|are you a robot|unusual traffic|verify you are human|"
    r"challenge-platform|cf-chl|bot detection|access denied|too many requests|"
    r"anomaly\.js|ddg-captcha)",
    re.IGNORECASE,
)

RESULT_MARKUP_PATTERNS = re.compile(
    r"(result__a|web-result|algo|compTitle|w-gl__result|snippet|"
    r"data-testid=[\"']result|class=[\"'][^\"']*result)",
    re.IGNORECASE,
)

REVIEW_INTENT_PATTERN = re.compile(
    r"\b(review|movie review|film review|rating|stars|verdict|critic)\b",
    re.IGNORECASE,
)

NON_ARTICLE_PATH_SEGMENTS = (
    "/search", "/tag/", "/tags/", "/topic/", "/topics/",
    "/photos/", "/videos/", "/gallery/", "/page/",
)

RAW_CSV_COLUMNS = [
    "ddgs_version",
    "python_version",
    "stage",
    "test_id",
    "backend_requested",
    "backend_actual",
    "region",
    "safesearch",
    "max_results",
    "timeout",
    "page",
    "header_profile",
    "headers_applied",
    "attempts_configured",
    "attempts_used",
    "retry_delay",
    "cooldown",
    "concurrency",
    "query_variant",
    "query",
    "expected_domain",
    "http_status",
    "final_url",
    "result_count",
    "genuine_review_count",
    "domain_match_count",
    "valid_url_count",
    "suspicious_title_count",
    "recognizable_markup",
    "parse_failed_on_200",
    "pagination_verified",
    "latency",
    "classification",
    "error_type",
    "error_message",
    "success",
    "genuine_review_found",
    "repeat_run",
    "timestamp_utc",
]

FINAL_REPORT_COLUMNS = [
    "DDGS version",
    "Python version",
    "Stage",
    "Backend",
    "Actual backend",
    "Region",
    "Safe search",
    "Max results",
    "Timeout",
    "Page",
    "Header profile",
    "Headers applied",
    "Attempts",
    "Retry delay",
    "Cooldown",
    "Concurrency",
    "Query",
    "HTTP status",
    "Final URL",
    "Result count",
    "Genuine reviews",
    "Recognizable markup",
    "Parse failed on 200",
    "Pagination verified",
    "Latency",
    "Classification",
    "Error type",
    "Error message",
    "Success",
    "Genuine review found",
    "Repeat run",
]


# ============================================================
# SHARED UTILITIES
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def print_banner(title: str, char: str = "=", width: int = 96) -> None:
    print(char * width, flush=True)
    print(title, flush=True)
    print(char * width, flush=True)


def gha_group_start(title: str, use_gha: bool) -> None:
    if use_gha:
        print(f"::group::{title}", flush=True)
    else:
        print_banner(title, char="=")


def gha_group_end(use_gha: bool) -> None:
    if use_gha:
        print("::endgroup::", flush=True)


def safe_pkg_version(name: str) -> str | None:
    try:
        return pkg_version(name)
    except PackageNotFoundError:
        return None


def to_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "yes")


def to_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def to_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def build_query_variants(movie: str, year: str, publisher: str, domain: str) -> dict[str, str]:
    """
    Spec Section 8: Maintain all mandatory signals (movie, year, review intent, publisher/site).
    Vary ONLY quoted/unquoted title and publisher name vs site:domain.
    """
    return {
        "unquoted_publisher": f"{movie} {year} movie review {publisher}",
        "quoted_publisher": f'"{movie}" {year} movie review {publisher}',
        "unquoted_site": f"{movie} {year} movie review site:{domain}",
        "quoted_site": f'"{movie}" {year} movie review site:{domain}',
    }


def get_domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except Exception:
        return False


def matches_domain(url: str, expected_domain: str | None) -> bool | None:
    if not expected_domain:
        return None
    actual = get_domain(url)
    expected = expected_domain.lower().removeprefix("www.")
    return actual == expected or actual.endswith("." + expected)


def analyze_result(raw: dict[str, Any], movie: str, expected_domain: str | None) -> dict[str, Any]:
    title = str(raw.get("title") or "").strip()
    url = str(raw.get("href") or raw.get("url") or "").strip()
    snippet = str(raw.get("body") or raw.get("snippet") or "").strip()

    valid = is_valid_url(url)
    domain = get_domain(url)
    dom_match = matches_domain(url, expected_domain)
    suspicious = len(title) > 160 or title.count("...") >= 3

    parsed = urlparse(url) if valid else None
    path = (parsed.path or "").lower() if parsed else ""
    is_article_path = bool(path and path not in ("/", "")) and not any(
        seg in path for seg in NON_ARTICLE_PATH_SEGMENTS
    )

    combined = f"{title} {url} {snippet}".lower()
    movie_tokens = [tok for tok in re.findall(r"[a-z0-9]+", movie.lower()) if len(tok) >= 2]
    movie_match = all(tok in combined for tok in movie_tokens) if movie_tokens else True
    review_signal = bool(REVIEW_INTENT_PATTERN.search(f"{title} {path} {snippet}"))

    genuine_review = bool(
        valid
        and not suspicious
        and is_article_path
        and movie_match
        and review_signal
        and (dom_match is True if expected_domain else True)
    )

    return {
        "title": title,
        "url": url,
        "snippet": snippet[:220],
        "domain": domain,
        "valid_url": valid,
        "domain_match": dom_match,
        "suspicious_title": suspicious,
        "is_article_path": is_article_path,
        "movie_match": movie_match,
        "review_signal": review_signal,
        "genuine_review": genuine_review,
    }


# ============================================================
# WORKER: RUNTIME INTROSPECTION & HTTP INSTRUMENTATION
# ============================================================

@dataclass
class HttpTraceEvent:
    engine_name: str
    engine_provider: str | None
    method: str
    url: str
    final_url: str
    status_code: int | None
    request_headers: dict[str, Any]
    headers_injected: dict[str, str]
    headers_supported: bool
    response_bytes: int
    recognizable_markup: bool
    antibot_detected: bool
    xpath_hits: int | None
    elapsed: float
    exception_type: str | None = None
    exception_message: str | None = None


class DDGSInspector:
    """
    Instruments BaseSearchEngine.search and HttpClient.request to expose:
    - Actual backend engine executed (even when backend='auto')
    - Real HTTP status codes (200/202/403/429) swallowed by DDGS exceptions
    - Final response URL, response size, recognizable markup, and XPath hit count
    - Whether custom request headers are supported and actually sent
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self._lock = threading.Lock()
        self._tls = threading.local()
        self._traces_by_query: dict[str, list[HttpTraceEvent]] = {}
        self._header_overrides_by_query: dict[str, dict[str, str]] = {}
        self._installed = False
        self.http_client_supports_headers = False
        self.http_client_class_name = "unknown"
        self.http_client_backend_pkg = "unknown"
        self.engine_classes: dict[str, Any] = {}
        self.text_signature: inspect.Signature | None = None

    def inspect_environment(self) -> dict[str, Any]:
        import ddgs
        from ddgs import DDGS

        self.text_signature = inspect.signature(DDGS.text)
        self.engine_classes = self._discover_registered_text_backends()

        http_candidates = ["primp", "httpx", "curl_cffi", "aiohttp", "requests"]
        detected_http_pkgs = {
            name: ver for name in http_candidates if (ver := safe_pkg_version(name)) is not None
        }

        try:
            from ddgs.http_client import HttpClient

            self.http_client_class_name = f"{HttpClient.__module__}.{HttpClient.__name__}"
            req_sig = inspect.signature(HttpClient.request)
            params = req_sig.parameters
            self.http_client_supports_headers = (
                "headers" in params
                or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
            )
            src_hint = ""
            try:
                src_hint = inspect.getsource(HttpClient)
            except Exception:
                pass
            for lib in ("primp", "httpx", "curl_cffi"):
                if lib in src_hint:
                    self.http_client_backend_pkg = f"{lib}=={detected_http_pkgs.get(lib, 'unknown')}"
                    break
            else:
                if detected_http_pkgs:
                    first_k, first_v = next(iter(detected_http_pkgs.items()))
                    self.http_client_backend_pkg = f"{first_k}=={first_v}"
        except Exception as exc:
            self.http_client_class_name = f"unavailable ({exc})"

        return {
            "timestamp_utc": utc_now(),
            "python_version": platform.python_version(),
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "github_actions": os.environ.get("GITHUB_ACTIONS", "false"),
            "runner_os": os.environ.get("RUNNER_OS", ""),
            "runner_arch": os.environ.get("RUNNER_ARCH", ""),
            "ddgs_version": getattr(ddgs, "__version__", None) or safe_pkg_version("ddgs") or "unknown",
            "http_client_class": self.http_client_class_name,
            "http_client_package": self.http_client_backend_pkg,
            "detected_http_packages": detected_http_pkgs,
            "http_client_supports_headers": self.http_client_supports_headers,
            "text_method_signature": str(self.text_signature),
            "registered_text_backends": sorted(self.engine_classes.keys()),
        }

    def _discover_registered_text_backends(self) -> dict[str, Any]:
        found: dict[str, Any] = {}
        try:
            from ddgs.engines import ENGINES

            text_map = ENGINES.get("text", {})
            if isinstance(text_map, dict):
                for k, v in text_map.items():
                    found[str(k)] = v
        except Exception:
            pass

        if not found:
            try:
                from ddgs.base import BaseSearchEngine

                for cls in BaseSearchEngine.__subclasses__():
                    if getattr(cls, "category", None) == "text":
                        name = getattr(cls, "name", cls.__name__.lower())
                        found[str(name)] = cls
            except Exception:
                pass
        return found

    def install_hooks(self) -> None:
        if self._installed:
            return
        inspector = self
        try:
            from ddgs.base import BaseSearchEngine
            from ddgs.http_client import HttpClient
        except Exception as exc:
            self.logger.warning("Could not hook DDGS internals (%s); continuing without HTTP trace hooks.", exc)
            return

        orig_search = BaseSearchEngine.search
        orig_http_request = HttpClient.request

        def patched_search(engine_self: Any, query: str, *args: Any, **kwargs: Any) -> Any:
            inspector._tls.query = query
            inspector._tls.engine_name = getattr(engine_self, "name", type(engine_self).__name__.lower())
            inspector._tls.engine_provider = getattr(engine_self, "provider", None)
            inspector._tls.engine_ref = engine_self
            try:
                return orig_search(engine_self, query, *args, **kwargs)
            finally:
                inspector._tls.query = None
                inspector._tls.engine_name = None
                inspector._tls.engine_provider = None
                inspector._tls.engine_ref = None

        def patched_http_request(http_self: Any, *args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            query = getattr(inspector._tls, "query", None) or "__unknown__"
            engine_name = getattr(inspector._tls, "engine_name", None) or "unknown"
            engine_provider = getattr(inspector._tls, "engine_provider", None)
            engine_ref = getattr(inspector._tls, "engine_ref", None)

            method = str(kwargs.get("method") or (args[0] if len(args) > 0 else "GET")).upper()
            url = str(kwargs.get("url") or (args[1] if len(args) > 1 else ""))

            injected: dict[str, str] = {}
            with inspector._lock:
                profile_headers = inspector._header_overrides_by_query.get(query)

            headers_supported = inspector.http_client_supports_headers
            if profile_headers and headers_supported:
                merged = dict(kwargs.get("headers") or {})
                for hk, hv in profile_headers.items():
                    if hk == "__dynamic_referer__":
                        parsed_origin = urlparse(url)
                        if parsed_origin.scheme and parsed_origin.netloc:
                            ref_val = f"{parsed_origin.scheme}://{parsed_origin.netloc}/"
                            merged["Referer"] = ref_val
                            injected["Referer"] = ref_val
                    else:
                        merged[hk] = hv
                        injected[hk] = hv
                kwargs["headers"] = merged

            req_headers_snapshot = dict(kwargs.get("headers") or {})
            try:
                resp = orig_http_request(http_self, *args, **kwargs)
                elapsed = time.perf_counter() - start

                status_code = getattr(resp, "status_code", None)
                final_url = str(getattr(resp, "url", "") or url)
                content = getattr(resp, "content", b"") or b""
                if isinstance(content, str):
                    text_body = content
                    body_len = len(content.encode("utf-8", errors="ignore"))
                else:
                    body_len = len(content)
                    text_body = getattr(resp, "text", None)
                    if not isinstance(text_body, str):
                        text_body = content.decode("utf-8", errors="ignore")

                antibot = bool(status_code == 202 or ANTIBOT_PATTERNS.search(text_body[:40000]))
                xpath_hits = inspector._count_xpath_hits(engine_ref, text_body)
                recognizable = bool(
                    (xpath_hits is not None and xpath_hits > 0)
                    or RESULT_MARKUP_PATTERNS.search(text_body[:80000])
                )

                inspector._record_event(
                    query,
                    HttpTraceEvent(
                        engine_name=engine_name,
                        engine_provider=engine_provider,
                        method=method,
                        url=url,
                        final_url=final_url,
                        status_code=status_code,
                        request_headers=req_headers_snapshot,
                        headers_injected=injected,
                        headers_supported=headers_supported,
                        response_bytes=body_len,
                        recognizable_markup=recognizable,
                        antibot_detected=antibot,
                        xpath_hits=xpath_hits,
                        elapsed=round(elapsed, 3),
                    ),
                )
                return resp

            except Exception as exc:
                elapsed = time.perf_counter() - start
                inspector._record_event(
                    query,
                    HttpTraceEvent(
                        engine_name=engine_name,
                        engine_provider=engine_provider,
                        method=method,
                        url=url,
                        final_url=url,
                        status_code=None,
                        request_headers=req_headers_snapshot,
                        headers_injected=injected,
                        headers_supported=headers_supported,
                        response_bytes=0,
                        recognizable_markup=False,
                        antibot_detected=False,
                        xpath_hits=None,
                        elapsed=round(elapsed, 3),
                        exception_type=type(exc).__name__,
                        exception_message=str(exc)[:300],
                    ),
                )
                raise

        BaseSearchEngine.search = patched_search
        HttpClient.request = patched_http_request
        self._installed = True

    @staticmethod
    def _count_xpath_hits(engine_ref: Any, html_text: str) -> int | None:
        if engine_ref is None or not html_text:
            return None
        items_xpath = getattr(engine_ref, "items_xpath", None)
        if not items_xpath:
            return None
        try:
            from lxml import html as lxml_html

            return len(lxml_html.fromstring(html_text).xpath(items_xpath))
        except Exception:
            return None

    def _record_event(self, query: str, event: HttpTraceEvent) -> None:
        with self._lock:
            self._traces_by_query.setdefault(query, []).append(event)

    def prepare_query(self, query: str, header_override: dict[str, str] | None) -> None:
        with self._lock:
            self._traces_by_query[query] = []
            if header_override:
                self._header_overrides_by_query[query] = header_override
            else:
                self._header_overrides_by_query.pop(query, None)

    def consume_traces(self, query: str) -> list[HttpTraceEvent]:
        with self._lock:
            self._header_overrides_by_query.pop(query, None)
            return self._traces_by_query.pop(query, [])


class IncrementalWriter:
    def __init__(self, csv_path: Path, jsonl_path: Path) -> None:
        self.csv_path = csv_path
        self.jsonl_path = jsonl_path
        self._lock = threading.Lock()
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=RAW_CSV_COLUMNS).writeheader()
        self.jsonl_path.write_text("", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        with self._lock:
            row = {col: record.get(col, "") for col in RAW_CSV_COLUMNS}
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=RAW_CSV_COLUMNS).writerow(row)
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ============================================================
# WORKER: CLASSIFICATION & TEST EXECUTION
# ============================================================

def classify_outcome(
    analyzed_results: list[dict[str, Any]],
    traces: list[HttpTraceEvent],
    exc_type: str | None,
    exc_msg: str | None,
) -> tuple[str, bool, bool]:
    """
    Spec Section 12 6-way distinction:
      1. HTTP_NETWORK_FAILURE
      2. HTTP_202_ANTIBOT
      3. HTTP_429_RATE_LIMIT
      4. HTTP_200_ZERO_PARSED
      5. SUCCESS_ZERO_GENUINE_REVIEWS
      6. SUCCESS_GENUINE_EDITORIAL_REVIEW
    """
    statuses = [t.status_code for t in traces if t.status_code is not None]
    has_200 = 200 in statuses
    has_202 = 202 in statuses
    has_429 = 429 in statuses
    any_antibot = any(t.antibot_detected for t in traces)
    any_markup = any(t.recognizable_markup for t in traces)

    if analyzed_results:
        if any(r["genuine_review"] for r in analyzed_results):
            return "SUCCESS_GENUINE_EDITORIAL_REVIEW", False, False
        return "SUCCESS_ZERO_GENUINE_REVIEWS", False, False

    if has_429 or (exc_type and "ratelimit" in exc_type.lower()) or (exc_msg and "429" in exc_msg):
        return "HTTP_429_RATE_LIMIT", False, False

    if has_202 or any_antibot or (exc_msg and "202" in exc_msg):
        return "HTTP_202_ANTIBOT", False, False

    if has_200:
        return "HTTP_200_ZERO_PARSED", True, bool(any_markup or not any_antibot)

    return "HTTP_NETWORK_FAILURE", False, False


def execute_single_test(
    inspector: DDGSInspector,
    env_info: dict[str, Any],
    logger: logging.Logger,
    *,
    stage: str,
    test_id: str,
    backend: str,
    region: str | None,
    safesearch: str,
    max_results: int,
    timeout: int,
    page: int,
    header_profile: str,
    attempts: int,
    retry_delay: int,
    cooldown: int,
    concurrency: int,
    query_variant: str,
    query: str,
    movie: str,
    expected_domain: str | None,
    repeat_run: int = 1,
    print_top_results: int = 3,
) -> dict[str, Any]:
    from ddgs import DDGS

    header_override = HEADER_PROFILES.get(header_profile)
    overall_start = time.perf_counter()

    attempt_history: list[dict[str, Any]] = []
    final_analyzed: list[dict[str, Any]] = []
    final_traces: list[HttpTraceEvent] = []
    last_exc_type: str | None = None
    last_exc_msg: str | None = None
    final_classification = "HTTP_NETWORK_FAILURE"
    parse_failed_on_200 = False

    region_display = "None(default)" if region is None else region
    logger.info(
        "[%s | %s] backend=%s region=%s safe=%s max=%d to=%ds pg=%d hdr=%s att=%d rdel=%ds cd=%ds conc=%d | q=%s",
        stage, test_id, backend, region_display, safesearch, max_results,
        timeout, page, header_profile, attempts, retry_delay, cooldown, concurrency, query,
    )

    sig_params = inspector.text_signature.parameters if inspector.text_signature else {}
    supports_page_arg = "page" in sig_params or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig_params.values()
    )

    for attempt_idx in range(1, attempts + 1):
        inspector.prepare_query(query, header_override)
        attempt_start = time.perf_counter()
        raw_results: list[dict[str, Any]] = []
        exc_type: str | None = None
        exc_msg: str | None = None

        try:
            text_kwargs: dict[str, Any] = {
                "backend": backend,
                "safesearch": safesearch,
                "max_results": max_results,
            }
            if region is not None:
                text_kwargs["region"] = region
            if supports_page_arg:
                text_kwargs["page"] = page

            with DDGS(timeout=timeout) as client:
                raw_iter = client.text(query, **text_kwargs)
                raw_results = list(raw_iter) if raw_iter else []
        except Exception as exc:
            exc_type = type(exc).__name__
            exc_msg = str(exc)[:400]

        attempt_elapsed = round(time.perf_counter() - attempt_start, 3)
        traces = inspector.consume_traces(query)
        analyzed = [analyze_result(r, movie, expected_domain) for r in raw_results]

        classification, parse_fail_200, is_parser_failure = classify_outcome(
            analyzed, traces, exc_type, exc_msg
        )

        statuses_str = ",".join(
            str(t.status_code) if t.status_code is not None else "ERR" for t in traces
        ) or "NONE"
        actual_backends_str = ",".join(
            dict.fromkeys(t.engine_name for t in traces if t.engine_name)
        ) or "none"

        logger.info(
            "  -> attempt %d/%d | class=%s | actual=%s | http=%s | res=%d | genuine=%d | "
            "markup=%s | parse_fail_200=%s | %.2fs%s",
            attempt_idx, attempts, classification, actual_backends_str, statuses_str,
            len(analyzed), sum(1 for a in analyzed if a["genuine_review"]),
            any(t.recognizable_markup for t in traces), parse_fail_200, attempt_elapsed,
            f" | err={exc_type}: {exc_msg}" if exc_type else "",
        )

        attempt_history.append({
            "attempt": attempt_idx,
            "classification": classification,
            "http_statuses": statuses_str,
            "actual_backends": actual_backends_str,
            "result_count": len(analyzed),
            "elapsed": attempt_elapsed,
            "error_type": exc_type,
            "error_message": exc_msg,
        })

        final_analyzed = analyzed
        final_traces = traces
        last_exc_type = exc_type
        last_exc_msg = exc_msg
        final_classification = classification
        parse_failed_on_200 = parse_fail_200

        if analyzed:
            break

        # Spec Section 10: Never mask parser failures with retries
        if is_parser_failure:
            logger.warning("  -> HTTP 200 with 0 parsed results; stopping retries to avoid masking parser failure.")
            break

        if exc_type in ("TypeError", "ValueError", "KeyError"):
            logger.warning("  -> Parameter error (%s); skipping retries.", exc_type)
            break

        if attempt_idx < attempts:
            logger.info("  -> Retry delay: sleeping %ds before attempt %d", retry_delay, attempt_idx + 1)
            time.sleep(retry_delay)

    total_latency = round(time.perf_counter() - overall_start, 3)

    if final_analyzed and print_top_results > 0:
        for idx, item in enumerate(final_analyzed[:print_top_results], start=1):
            logger.info(
                "     [%d] genuine=%s domain_match=%s | %s | %s",
                idx,
                "YES" if item["genuine_review"] else "NO",
                "YES" if item["domain_match"] else ("N/A" if item["domain_match"] is None else "NO"),
                item["title"][:90],
                item["url"],
            )

    actual_backends = list(dict.fromkeys(t.engine_name for t in final_traces if t.engine_name))
    http_statuses = [str(t.status_code) for t in final_traces if t.status_code is not None]
    final_urls = list(dict.fromkeys(t.final_url for t in final_traces if t.final_url))
    headers_applied = any(bool(t.headers_injected) for t in final_traces)
    recognizable_markup = any(t.recognizable_markup for t in final_traces)

    genuine_count = sum(1 for r in final_analyzed if r["genuine_review"])
    domain_match_count = sum(1 for r in final_analyzed if r["domain_match"] is True)
    valid_url_count = sum(1 for r in final_analyzed if r["valid_url"])
    suspicious_count = sum(1 for r in final_analyzed if r["suspicious_title"])

    success = final_classification in (
        "SUCCESS_GENUINE_EDITORIAL_REVIEW",
        "SUCCESS_ZERO_GENUINE_REVIEWS",
    )

    return {
        "ddgs_version": env_info["ddgs_version"],
        "python_version": env_info["python_version"],
        "stage": stage,
        "test_id": test_id,
        "backend_requested": backend,
        "backend_actual": ",".join(actual_backends) if actual_backends else "none",
        "region": region_display,
        "safesearch": safesearch,
        "max_results": max_results,
        "timeout": timeout,
        "page": page,
        "header_profile": header_profile,
        "headers_applied": headers_applied,
        "attempts_configured": attempts,
        "attempts_used": len(attempt_history),
        "retry_delay": retry_delay,
        "cooldown": cooldown,
        "concurrency": concurrency,
        "query_variant": query_variant,
        "query": query,
        "expected_domain": expected_domain or "",
        "http_status": ",".join(http_statuses) if http_statuses else "NONE",
        "final_url": final_urls[-1] if final_urls else "",
        "result_count": len(final_analyzed),
        "genuine_review_count": genuine_count,
        "domain_match_count": domain_match_count,
        "valid_url_count": valid_url_count,
        "suspicious_title_count": suspicious_count,
        "recognizable_markup": recognizable_markup,
        "parse_failed_on_200": parse_failed_on_200,
        "pagination_verified": "",
        "latency": total_latency,
        "classification": final_classification,
        "error_type": last_exc_type or "",
        "error_message": last_exc_msg or "",
        "success": success,
        "genuine_review_found": genuine_count > 0,
        "repeat_run": repeat_run,
        "timestamp_utc": utc_now(),
        "results": final_analyzed,
        "http_traces": [asdict(t) for t in final_traces],
        "attempt_history": attempt_history,
    }


# ============================================================
# WORKER: STAGED EXPERIMENT (SPEC SECTION 13)
# ============================================================

def run_worker(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
        force=True,
    )
    for noisy in ("primp", "httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logger = logging.getLogger("ddgs-worker")

    use_gha = args.gha_groups or (os.environ.get("GITHUB_ACTIONS", "").lower() == "true")
    out_dir = Path(args.worker_output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    inspector = DDGSInspector(logger)
    env_info = inspector.inspect_environment()
    inspector.install_hooks()

    ddgs_ver = env_info["ddgs_version"]
    py_ver = env_info["python_version"]
    safe_ver_tag = re.sub(r"[^a-zA-Z0-9._-]", "_", ddgs_ver)

    csv_path = out_dir / f"results_py{py_ver}_ddgs{safe_ver_tag}.csv"
    jsonl_path = out_dir / f"results_py{py_ver}_ddgs{safe_ver_tag}.jsonl"
    meta_path = out_dir / f"env_py{py_ver}_ddgs{safe_ver_tag}.json"
    writer = IncrementalWriter(csv_path, jsonl_path)

    gha_group_start(f"ENVIRONMENT | Python {py_ver} | DDGS {ddgs_ver}", use_gha)
    for k, v in env_info.items():
        print(f"  {k:<30}: {v}", flush=True)
    gha_group_end(use_gha)

    registered_backends = env_info["registered_text_backends"]
    registered_set = set(registered_backends)

    supported_to_test: list[str] = ["auto"]
    unsupported_candidates: list[str] = []

    for candidate in CANDIDATE_BACKENDS:
        if candidate == "auto":
            continue
        if candidate in registered_set:
            supported_to_test.append(candidate)
        else:
            unsupported_candidates.append(candidate)

    for reg_name in registered_backends:
        if reg_name not in supported_to_test:
            supported_to_test.append(reg_name)

    env_info["supported_backends_tested"] = supported_to_test
    env_info["unsupported_candidate_backends"] = unsupported_candidates
    meta_path.write_text(json.dumps(env_info, indent=2), encoding="utf-8")

    logger.info("Registered text backends   : %s", registered_backends)
    logger.info("Supported backends to test : %s", supported_to_test)
    logger.info("Unsupported (recorded only): %s", unsupported_candidates)

    all_records: list[dict[str, Any]] = []
    baseline_queries = build_query_variants(
        BASELINE_MOVIE["movie"],
        BASELINE_MOVIE["year"],
        BASELINE_MOVIE["publisher"],
        BASELINE_MOVIE["domain"],
    )
    baseline_query = baseline_queries["quoted_site"]
    base_cooldown = args.base_cooldown
    stages_enabled = set(args.stages)

    # Record unregistered backends explicitly without invoking them
    for idx, unsup in enumerate(unsupported_candidates, start=1):
        rec = {
            "ddgs_version": ddgs_ver,
            "python_version": py_ver,
            "stage": "S1_UNSUPPORTED",
            "test_id": f"S1-UNSUP-{idx}",
            "backend_requested": unsup,
            "backend_actual": "UNREGISTERED",
            "region": "in-en",
            "safesearch": "moderate",
            "max_results": 10,
            "timeout": 20,
            "page": 1,
            "header_profile": "default",
            "headers_applied": False,
            "attempts_configured": 0,
            "attempts_used": 0,
            "retry_delay": 0,
            "cooldown": 0,
            "concurrency": 1,
            "query_variant": "quoted_site",
            "query": baseline_query,
            "expected_domain": BASELINE_MOVIE["domain"],
            "http_status": "SKIPPED",
            "final_url": "",
            "result_count": 0,
            "genuine_review_count": 0,
            "domain_match_count": 0,
            "valid_url_count": 0,
            "suspicious_title_count": 0,
            "recognizable_markup": False,
            "parse_failed_on_200": False,
            "pagination_verified": "",
            "latency": 0.0,
            "classification": "UNSUPPORTED_BACKEND",
            "error_type": "BackendNotRegistered",
            "error_message": f"Backend '{unsup}' is not registered in ddgs {ddgs_ver}",
            "success": False,
            "genuine_review_found": False,
            "repeat_run": 1,
            "timestamp_utc": utc_now(),
        }
        writer.write(rec)
        all_records.append(rec)

    # STAGE 1: Baseline Backends
    working_backends: list[str] = []
    if 1 in stages_enabled:
        gha_group_start(f"STAGE 1: Baseline Backends ({len(supported_to_test)} backends)", use_gha)
        for idx, backend in enumerate(supported_to_test, start=1):
            rec = execute_single_test(
                inspector, env_info, logger,
                stage="S1_BACKEND_BASELINE", test_id=f"S1-B{idx}",
                backend=backend, region="in-en", safesearch="moderate",
                max_results=10, timeout=20, page=1, header_profile="default",
                attempts=1, retry_delay=2, cooldown=base_cooldown, concurrency=1,
                query_variant="quoted_site", query=baseline_query,
                movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
            )
            writer.write(rec)
            all_records.append(rec)
            if rec["success"]:
                working_backends.append(backend)
            if idx < len(supported_to_test) and base_cooldown > 0:
                time.sleep(base_cooldown)
        gha_group_end(use_gha)

    if not working_backends:
        logger.warning("Stage 1 found 0 working backends; falling back to first 2 registered backends for diagnostics.")
        working_backends = supported_to_test[:2]
    else:
        working_backends = working_backends[: args.max_working_backends]

    logger.info("Selected backends for Stages 2-5: %s", working_backends)

    best_params: dict[str, dict[str, Any]] = {
        b: {"region": "in-en", "safesearch": "moderate", "max_results": 10, "timeout": 20}
        for b in working_backends
    }

    # STAGE 2: Region, SafeSearch, MaxResults, Timeout, Pagination
    if 2 in stages_enabled:
        gha_group_start("STAGE 2: Region / SafeSearch / MaxResults / Timeout / Pagination", use_gha)
        regions_to_run = REGIONS[:4] if args.quick else REGIONS
        max_results_to_run = [5, 10, 30] if args.quick else MAX_RESULTS_VALUES
        timeouts_to_run = [10, 20, 45] if args.quick else TIMEOUT_VALUES
        pages_to_run = [1, 2] if args.quick else PAGE_VALUES

        for backend in working_backends:
            # 2A: Region
            best_reg_score = (-1, -1, -9999.0)
            for idx, reg in enumerate(regions_to_run, start=1):
                rec = execute_single_test(
                    inspector, env_info, logger,
                    stage="S2_REGION", test_id=f"S2-REG-{backend}-{idx}",
                    backend=backend, region=reg, safesearch="moderate",
                    max_results=10, timeout=20, page=1, header_profile="default",
                    attempts=1, retry_delay=2, cooldown=base_cooldown, concurrency=1,
                    query_variant="quoted_site", query=baseline_query,
                    movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
                    print_top_results=1,
                )
                writer.write(rec)
                all_records.append(rec)
                score = (int(rec["genuine_review_found"]), int(rec["success"]), -rec["latency"])
                if score > best_reg_score:
                    best_reg_score = score
                    best_params[backend]["region"] = reg
                if base_cooldown > 0:
                    time.sleep(base_cooldown)

            # 2B: SafeSearch
            best_safe_score = (-1, -1, -9999.0)
            for idx, safe in enumerate(SAFESEARCH_VALUES, start=1):
                rec = execute_single_test(
                    inspector, env_info, logger,
                    stage="S2_SAFESEARCH", test_id=f"S2-SAFE-{backend}-{idx}",
                    backend=backend, region=best_params[backend]["region"], safesearch=safe,
                    max_results=10, timeout=20, page=1, header_profile="default",
                    attempts=1, retry_delay=2, cooldown=base_cooldown, concurrency=1,
                    query_variant="quoted_site", query=baseline_query,
                    movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
                    print_top_results=1,
                )
                writer.write(rec)
                all_records.append(rec)
                score = (int(rec["genuine_review_found"]), int(rec["success"]), -rec["latency"])
                if score > best_safe_score:
                    best_safe_score = score
                    best_params[backend]["safesearch"] = safe
                if base_cooldown > 0:
                    time.sleep(base_cooldown)

            # 2C: Max results
            for idx, mr in enumerate(max_results_to_run, start=1):
                rec = execute_single_test(
                    inspector, env_info, logger,
                    stage="S2_MAX_RESULTS", test_id=f"S2-MAX-{backend}-{idx}",
                    backend=backend, region=best_params[backend]["region"],
                    safesearch=best_params[backend]["safesearch"], max_results=mr,
                    timeout=20, page=1, header_profile="default",
                    attempts=1, retry_delay=2, cooldown=base_cooldown, concurrency=1,
                    query_variant="quoted_site", query=baseline_query,
                    movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
                    print_top_results=0,
                )
                writer.write(rec)
                all_records.append(rec)
                if base_cooldown > 0:
                    time.sleep(base_cooldown)

            # 2D: Timeout
            for idx, to in enumerate(timeouts_to_run, start=1):
                rec = execute_single_test(
                    inspector, env_info, logger,
                    stage="S2_TIMEOUT", test_id=f"S2-TO-{backend}-{idx}",
                    backend=backend, region=best_params[backend]["region"],
                    safesearch=best_params[backend]["safesearch"], max_results=10,
                    timeout=to, page=1, header_profile="default",
                    attempts=1, retry_delay=2, cooldown=base_cooldown, concurrency=1,
                    query_variant="quoted_site", query=baseline_query,
                    movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
                    print_top_results=0,
                )
                writer.write(rec)
                all_records.append(rec)
                if base_cooldown > 0:
                    time.sleep(base_cooldown)

            # 2E: Pagination verification
            page1_urls: set[str] = set()
            for pg in pages_to_run:
                rec = execute_single_test(
                    inspector, env_info, logger,
                    stage="S2_PAGINATION", test_id=f"S2-PG-{backend}-P{pg}",
                    backend=backend, region=best_params[backend]["region"],
                    safesearch=best_params[backend]["safesearch"], max_results=10,
                    timeout=20, page=pg, header_profile="default",
                    attempts=1, retry_delay=2, cooldown=base_cooldown, concurrency=1,
                    query_variant="quoted_site", query=baseline_query,
                    movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
                    print_top_results=1,
                )
                curr_urls = {r["url"] for r in rec["results"] if r.get("url")}
                if pg == 1:
                    page1_urls = curr_urls
                    rec["pagination_verified"] = "BASE_PAGE"
                else:
                    if not curr_urls:
                        rec["pagination_verified"] = "NO_RESULTS"
                    elif curr_urls - page1_urls:
                        rec["pagination_verified"] = f"SUPPORTED ({len(curr_urls - page1_urls)} new URLs)"
                    else:
                        rec["pagination_verified"] = "DUPLICATE_PAGE_1"
                    logger.info("  -> Pagination check (page %d): %s", pg, rec["pagination_verified"])
                writer.write(rec)
                all_records.append(rec)
                if base_cooldown > 0:
                    time.sleep(base_cooldown)
        gha_group_end(use_gha)

    # STAGE 3: Request Headers, Retry, Cooldown, Concurrency
    if 3 in stages_enabled:
        gha_group_start("STAGE 3: Request Headers & Retry/Throttling/Concurrency", use_gha)
        header_backends = working_backends[:2]

        if not inspector.http_client_supports_headers:
            logger.warning("HttpClient does not expose headers parameter; skipping header overrides.")
        else:
            for backend in header_backends:
                bp = best_params[backend]
                for idx, hname in enumerate(HEADER_PROFILES.keys(), start=1):
                    rec = execute_single_test(
                        inspector, env_info, logger,
                        stage="S3_HEADERS", test_id=f"S3-HDR-{backend}-{idx}",
                        backend=backend, region=bp["region"], safesearch=bp["safesearch"],
                        max_results=10, timeout=20, page=1, header_profile=hname,
                        attempts=1, retry_delay=2, cooldown=base_cooldown, concurrency=1,
                        query_variant="quoted_site", query=baseline_query,
                        movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
                        print_top_results=1,
                    )
                    writer.write(rec)
                    all_records.append(rec)
                    if base_cooldown > 0:
                        time.sleep(base_cooldown)

        primary_backend = working_backends[0]
        bp0 = best_params[primary_backend]

        # 3B: Retry pairs
        retry_pairs = RETRY_PAIRS_QUICK if args.quick else RETRY_PAIRS_FULL
        for idx, (att, rdelay) in enumerate(retry_pairs, start=1):
            rec = execute_single_test(
                inspector, env_info, logger,
                stage="S3_RETRY", test_id=f"S3-RET-{primary_backend}-{idx}",
                backend=primary_backend, region=bp0["region"], safesearch=bp0["safesearch"],
                max_results=10, timeout=20, page=1, header_profile="default",
                attempts=att, retry_delay=rdelay, cooldown=base_cooldown, concurrency=1,
                query_variant="quoted_site", query=baseline_query,
                movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
                print_top_results=0,
            )
            writer.write(rec)
            all_records.append(rec)
            if base_cooldown > 0:
                time.sleep(base_cooldown)

        # 3C: Cooldown sweep
        cooldown_vals = [0, 2, 8] if args.quick else COOLDOWN_VALUES
        burst_queries = [
            ("Dangal", "hindustantimes.com", '"Dangal" 2016 movie review site:hindustantimes.com'),
            ("3 Idiots", "hindustantimes.com", '"3 Idiots" 2009 movie review site:hindustantimes.com'),
        ]
        for cd in cooldown_vals:
            for b_idx, (mv, dom, bq) in enumerate(burst_queries, start=1):
                rec = execute_single_test(
                    inspector, env_info, logger,
                    stage="S3_COOLDOWN", test_id=f"S3-CD{cd}-{primary_backend}-Q{b_idx}",
                    backend=primary_backend, region=bp0["region"], safesearch=bp0["safesearch"],
                    max_results=10, timeout=20, page=1, header_profile="default",
                    attempts=1, retry_delay=2, cooldown=cd, concurrency=1,
                    query_variant="quoted_site", query=bq, movie=mv, expected_domain=dom,
                    print_top_results=0,
                )
                writer.write(rec)
                all_records.append(rec)
                if b_idx < len(burst_queries) and cd > 0:
                    time.sleep(cd)
            if base_cooldown > 0:
                time.sleep(base_cooldown)

        # 3D: Concurrency (distinct queries per thread to keep trace attribution clean)
        conc_queries = [
            ("Dangal", "hindustantimes.com", '"Dangal" 2016 movie review site:hindustantimes.com'),
            ("3 Idiots", "hindustantimes.com", '"3 Idiots" 2009 movie review site:hindustantimes.com'),
            ("Jawan", "timesofindia.indiatimes.com", '"Jawan" 2023 movie review site:timesofindia.indiatimes.com'),
        ]
        for conc in CONCURRENCY_VALUES:
            batch = conc_queries[:conc]
            logger.info("--- Concurrency=%d test on backend=%s ---", conc, primary_backend)
            with ThreadPoolExecutor(max_workers=conc) as pool:
                futures = [
                    pool.submit(
                        execute_single_test,
                        inspector, env_info, logger,
                        stage="S3_CONCURRENCY", test_id=f"S3-CONC{conc}-{primary_backend}-W{w_idx}",
                        backend=primary_backend, region=bp0["region"], safesearch=bp0["safesearch"],
                        max_results=10, timeout=20, page=1, header_profile="default",
                        attempts=1, retry_delay=2, cooldown=0, concurrency=conc,
                        query_variant="quoted_site", query=cq, movie=mv, expected_domain=dom,
                        print_top_results=0,
                    )
                    for w_idx, (mv, dom, cq) in enumerate(batch, start=1)
                ]
                for fut in as_completed(futures):
                    rec = fut.result()
                    writer.write(rec)
                    all_records.append(rec)
            if base_cooldown > 0:
                time.sleep(base_cooldown)
        gha_group_end(use_gha)

    # STAGE 4: Query Variations
    best_variant_by_backend: dict[str, str] = {}
    if 4 in stages_enabled:
        gha_group_start("STAGE 4: Query Variations (Quoted/Unquoted x Publisher/Site)", use_gha)
        for backend in working_backends:
            bp = best_params[backend]
            best_var_score = (-1, -1, -9999.0)
            best_var_name = "quoted_site"
            for idx, (vname, vquery) in enumerate(baseline_queries.items(), start=1):
                rec = execute_single_test(
                    inspector, env_info, logger,
                    stage="S4_QUERY_VARIANTS", test_id=f"S4-QV-{backend}-{idx}",
                    backend=backend, region=bp["region"], safesearch=bp["safesearch"],
                    max_results=10, timeout=20, page=1, header_profile="default",
                    attempts=2, retry_delay=5, cooldown=base_cooldown, concurrency=1,
                    query_variant=vname, query=vquery,
                    movie=BASELINE_MOVIE["movie"], expected_domain=BASELINE_MOVIE["domain"],
                    print_top_results=2,
                )
                writer.write(rec)
                all_records.append(rec)
                score = (int(rec["genuine_review_found"]), rec["genuine_review_count"], -rec["latency"])
                if score > best_var_score:
                    best_var_score = score
                    best_var_name = vname
                if base_cooldown > 0:
                    time.sleep(base_cooldown)
            best_variant_by_backend[backend] = best_var_name
            logger.info("Best query variant for %s: %s", backend, best_var_name)
        gha_group_end(use_gha)

    # STAGE 5: Multi-Movie & Multi-Publisher Repeated Validation
    if 5 in stages_enabled:
        gha_group_start("STAGE 5: Multi-Movie & Multi-Publisher Repeated Validation", use_gha)
        corpus = VALIDATION_CORPUS[:4] if args.quick else VALIDATION_CORPUS
        repeats = 1 if args.quick else args.repeats
        top_backends = working_backends[:2]

        for rep in range(1, repeats + 1):
            for backend in top_backends:
                bp = best_params[backend]
                vname = best_variant_by_backend.get(backend, "quoted_site")
                for c_idx, item in enumerate(corpus, start=1):
                    q_map = build_query_variants(
                        item["movie"], item["year"], item["publisher"], item["domain"]
                    )
                    rec = execute_single_test(
                        inspector, env_info, logger,
                        stage="S5_VALIDATION", test_id=f"S5-R{rep}-{backend}-C{c_idx}",
                        backend=backend, region=bp["region"], safesearch=bp["safesearch"],
                        max_results=10, timeout=25, page=1, header_profile="default",
                        attempts=2, retry_delay=5, cooldown=base_cooldown, concurrency=1,
                        query_variant=vname, query=q_map[vname],
                        movie=item["movie"], expected_domain=item["domain"],
                        repeat_run=rep, print_top_results=2,
                    )
                    writer.write(rec)
                    all_records.append(rec)
                    if base_cooldown > 0:
                        time.sleep(base_cooldown)
        gha_group_end(use_gha)

    executed = [r for r in all_records if r["stage"] != "S1_UNSUPPORTED"]
    total = len(executed)
    succ = sum(1 for r in executed if r["success"])
    genuine = sum(1 for r in executed if r["genuine_review_found"])

    print_banner(
        f"WORKER COMPLETE | Python {py_ver} | DDGS {ddgs_ver} | "
        f"Tests: {total} | Success: {succ}/{total} ({(succ / total * 100) if total else 0:.1f}%) | "
        f"Genuine Reviews: {genuine}/{total} ({(genuine / total * 100) if total else 0:.1f}%)"
    )
    return 0


# ============================================================
# ORCHESTRATOR: ISOLATED VENVS, STREAMING & FINAL RANKING
# ============================================================

def stream_subprocess(cmd: list[str], prefix: str = "") -> int:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(f"{prefix}{line}" if prefix else line)
        sys.stdout.flush()
    return proc.wait()


def venv_python_path(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def prepare_isolated_venv(venv_root: Path, ddgs_spec: str, reuse: bool) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", ddgs_spec)
    venv_dir = venv_root / f"venv_py{sys.version_info.major}.{sys.version_info.minor}_ddgs_{safe_name}"
    py_bin = venv_python_path(venv_dir)

    if not reuse or not py_bin.exists():
        print_banner(f"Creating isolated venv for ddgs ({ddgs_spec}) -> {venv_dir}", char="-")
        venv.EnvBuilder(with_pip=True, clear=not reuse).create(str(venv_dir))
    else:
        print(f"Reusing isolated venv: {venv_dir}", flush=True)

    pkg_arg = "ddgs" if ddgs_spec.lower() == "latest" else f"ddgs=={ddgs_spec}"
    install_cmd = [str(py_bin), "-m", "pip", "install", "--upgrade", pkg_arg]
    if ddgs_spec.lower() != "latest":
        install_cmd.append("--force-reinstall")

    rc = stream_subprocess(install_cmd, prefix=f"[pip:{ddgs_spec}] ")
    if rc != 0:
        raise RuntimeError(f"pip install {pkg_arg} failed with exit code {rc}")
    return py_bin


def load_all_results(input_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    envs: list[dict[str, Any]] = []
    for csv_file in sorted(input_dir.rglob("results_py*.csv")):
        with open(csv_file, "r", encoding="utf-8", newline="") as f:
            rows.extend(csv.DictReader(f))
    for env_file in sorted(input_dir.rglob("env_py*.json")):
        try:
            envs.append(json.loads(env_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return rows, envs


def compute_rankings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Spec Section 14 ranking:
      1. Genuine editorial review discovery rate (desc)
      2. Query success rate (desc)
      3. Reliability across repeated runs (desc)
      4. Average latency (asc)
    """
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("stage") == "S1_UNSUPPORTED" or r.get("classification") == "UNSUPPORTED_BACKEND":
            continue
        key = (
            r.get("ddgs_version", ""),
            r.get("python_version", ""),
            r.get("backend_requested", ""),
            r.get("region", ""),
            r.get("safesearch", ""),
            str(r.get("max_results", "")),
            str(r.get("timeout", "")),
            str(r.get("page", "")),
            r.get("header_profile", "default"),
        )
        grouped[key].append(r)

    ranked: list[dict[str, Any]] = []
    for key, items in grouped.items():
        total = len(items)
        success_count = sum(1 for i in items if to_bool(i.get("success")))
        genuine_count = sum(1 for i in items if to_bool(i.get("genuine_review_found")))
        latencies = [to_float(i.get("latency")) for i in items if to_float(i.get("latency")) > 0]
        avg_latency = round(statistics.mean(latencies), 3) if latencies else 999.0

        by_repeat: dict[str, list[bool]] = defaultdict(list)
        for i in items:
            by_repeat[str(i.get("repeat_run", "1"))].append(to_bool(i.get("success")))
        repeat_rates = [sum(v) / len(v) for v in by_repeat.values() if v]
        if len(repeat_rates) > 1:
            reliability = round(min(repeat_rates) * (1.0 - statistics.pstdev(repeat_rates)), 4)
        else:
            reliability = round((success_count / total) * (0.85 if total == 1 else 1.0), 4)

        ranked.append({
            "ddgs_version": key[0],
            "python_version": key[1],
            "backend": key[2],
            "region": key[3],
            "safesearch": key[4],
            "max_results": to_int(key[5]),
            "timeout": to_int(key[6]),
            "page": to_int(key[7]),
            "header_profile": key[8],
            "tests_run": total,
            "genuine_review_rate": round(genuine_count / total, 4),
            "query_success_rate": round(success_count / total, 4),
            "repeat_reliability": reliability,
            "avg_latency": avg_latency,
            "parse_fail_200_count": sum(1 for i in items if to_bool(i.get("parse_failed_on_200"))),
            "http_202_count": sum(1 for i in items if i.get("classification") == "HTTP_202_ANTIBOT"),
            "http_429_count": sum(1 for i in items if i.get("classification") == "HTTP_429_RATE_LIMIT"),
        })

    ranked.sort(
        key=lambda x: (
            -x["genuine_review_rate"],
            -x["query_success_rate"],
            -x["repeat_reliability"],
            x["avg_latency"],
        )
    )
    for idx, entry in enumerate(ranked, start=1):
        entry["rank"] = idx
    return ranked


def map_report_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "DDGS version": r.get("ddgs_version", ""),
        "Python version": r.get("python_version", ""),
        "Stage": r.get("stage", ""),
        "Backend": r.get("backend_requested", ""),
        "Actual backend": r.get("backend_actual", ""),
        "Region": r.get("region", ""),
        "Safe search": r.get("safesearch", ""),
        "Max results": r.get("max_results", ""),
        "Timeout": r.get("timeout", ""),
        "Page": r.get("page", ""),
        "Header profile": r.get("header_profile", ""),
        "Headers applied": r.get("headers_applied", ""),
        "Attempts": f"{r.get('attempts_used', '')}/{r.get('attempts_configured', '')}",
        "Retry delay": r.get("retry_delay", ""),
        "Cooldown": r.get("cooldown", ""),
        "Concurrency": r.get("concurrency", ""),
        "Query": r.get("query", ""),
        "HTTP status": r.get("http_status", ""),
        "Final URL": r.get("final_url", ""),
        "Result count": r.get("result_count", 0),
        "Genuine reviews": r.get("genuine_review_count", 0),
        "Recognizable markup": r.get("recognizable_markup", ""),
        "Parse failed on 200": r.get("parse_failed_on_200", ""),
        "Pagination verified": r.get("pagination_verified", ""),
        "Latency": r.get("latency", 0),
        "Classification": r.get("classification", ""),
        "Error type": r.get("error_type", ""),
        "Error message": r.get("error_message", ""),
        "Success": r.get("success", False),
        "Genuine review found": r.get("genuine_review_found", False),
        "Repeat run": r.get("repeat_run", 1),
    }


def export_reports(
    rows: list[dict[str, Any]],
    ranked: list[dict[str, Any]],
    envs: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_out = output_dir / "ddgs_diagnostic_report.csv"
    ranked_csv_out = output_dir / "ddgs_ranked_configs.csv"
    json_out = output_dir / "ddgs_diagnostic_summary.json"
    xlsx_out = output_dir / "ddgs_diagnostic_report.xlsx"

    mapped_rows = [map_report_row(r) for r in rows]

    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FINAL_REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(mapped_rows)

    ranked_cols = [
        "rank", "ddgs_version", "python_version", "backend", "region", "safesearch",
        "max_results", "timeout", "page", "header_profile", "tests_run",
        "genuine_review_rate", "query_success_rate", "repeat_reliability",
        "avg_latency", "parse_fail_200_count", "http_202_count", "http_429_count",
    ]
    with open(ranked_csv_out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ranked_cols)
        writer.writeheader()
        writer.writerows(ranked)

    json_out.write_text(
        json.dumps(
            {
                "generated_utc": utc_now(),
                "total_records": len(rows),
                "environments": envs,
                "top_25_configurations": ranked[:25],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    try:
        import openpyxl
        from openpyxl.styles import Font

        wb = openpyxl.Workbook()

        ws_rank = wb.active
        ws_rank.title = "Ranked_Configs"
        ws_rank.append(ranked_cols)
        for cell in ws_rank[1]:
            cell.font = Font(bold=True)
        for item in ranked:
            ws_rank.append([item.get(c, "") for c in ranked_cols])

        ws_all = wb.create_sheet("All_Tests")
        ws_all.append(FINAL_REPORT_COLUMNS)
        for cell in ws_all[1]:
            cell.font = Font(bold=True)
        for mr in mapped_rows:
            ws_all.append([mr.get(c, "") for c in FINAL_REPORT_COLUMNS])

        ws_env = wb.create_sheet("Environments")
        env_headers = [
            "ddgs_version", "python_version", "os", "http_client_package",
            "http_client_supports_headers", "registered_text_backends",
            "unsupported_candidate_backends",
        ]
        ws_env.append(env_headers)
        for cell in ws_env[1]:
            cell.font = Font(bold=True)
        for e in envs:
            ws_env.append([
                json.dumps(e.get(h, "")) if isinstance(e.get(h), (list, dict)) else e.get(h, "")
                for h in env_headers
            ])

        wb.save(xlsx_out)
        print(f"Excel report saved : {xlsx_out}", flush=True)
    except ImportError:
        print("openpyxl not installed; skipped .xlsx export (CSV & JSON exported).", flush=True)

    print(f"CSV report saved   : {csv_out}", flush=True)
    print(f"Ranked CSV saved   : {ranked_csv_out}", flush=True)
    print(f"JSON summary saved : {json_out}", flush=True)


def print_leaderboard(ranked: list[dict[str, Any]], top_n: int = 20) -> None:
    print_banner("TOP RANKED DDGS CONFIGURATIONS (GENUINE REVIEW -> SUCCESS -> RELIABILITY -> LATENCY)")
    header = (
        f"{'RNK':<4} {'DDGS':<8} {'PY':<7} {'BACKEND':<12} {'REGION':<13} "
        f"{'SAFE':<9} {'MAX':<4} {'TO':<3} {'PG':<3} {'N':<3} "
        f"{'GEN%':<7} {'SUC%':<7} {'REL%':<7} {'LAT(s)':<7}"
    )
    print(header, flush=True)
    print("-" * len(header), flush=True)
    for item in ranked[:top_n]:
        print(
            f"{item['rank']:<4} "
            f"{item['ddgs_version']:<8} "
            f"{item['python_version']:<7} "
            f"{item['backend']:<12} "
            f"{item['region']:<13} "
            f"{item['safesearch']:<9} "
            f"{item['max_results']:<4} "
            f"{item['timeout']:<3} "
            f"{item['page']:<3} "
            f"{item['tests_run']:<3} "
            f"{item['genuine_review_rate'] * 100:<7.1f} "
            f"{item['query_success_rate'] * 100:<7.1f} "
            f"{item['repeat_reliability'] * 100:<7.1f} "
            f"{item['avg_latency']:<7.2f}",
            flush=True,
        )


def run_orchestrator(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)

    if args.merge_only:
        rows, envs = load_all_results(Path(args.merge_only))
        ranked = compute_rankings(rows)
        export_reports(rows, ranked, envs, output_dir)
        print_leaderboard(ranked)
        return 0

    this_script = Path(__file__).resolve()
    venv_root = Path(args.venv_dir)
    venv_root.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []

    for ver in args.versions:
        print_banner(f"ISOLATED RUN | Python {sys.version.split()[0]} | DDGS target={ver}")
        try:
            py_bin = prepare_isolated_venv(venv_root, ver, reuse=args.reuse_venvs)
            cmd = [
                str(py_bin),
                "-u",
                str(this_script),
                "--worker",
                "--worker-output-dir", str(raw_dir),
                "--base-cooldown", str(args.base_cooldown),
                "--max-working-backends", str(args.max_working_backends),
                "--repeats", str(args.repeats),
                "--stages", *[str(s) for s in args.stages],
            ]
            if args.quick:
                cmd.append("--quick")
            if args.gha_groups or os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
                cmd.append("--gha-groups")

            rc = stream_subprocess(cmd, prefix=f"[ddgs:{ver}] ")
            if rc != 0:
                failures.append(f"ddgs=={ver} exited with {rc}")
        except Exception as exc:
            print(f"[ddgs:{ver}] FAILED: {exc}", flush=True)
            failures.append(f"ddgs=={ver}: {exc}")

    rows, envs = load_all_results(raw_dir)
    ranked = compute_rankings(rows)
    export_reports(rows, ranked, envs, output_dir)
    print_leaderboard(ranked)

    if failures:
        print_banner("WARNINGS / VERSION FAILURES", char="!")
        for f in failures:
            print(f"  - {f}", flush=True)

    return 0 if rows else 1


# ============================================================
# CLI ENTRYPOINT
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Single-file isolated DDGS staged diagnostic suite")
    parser.add_argument("--versions", nargs="+", default=DEFAULT_DDGS_VERSIONS, help="DDGS versions to test")
    parser.add_argument("--venv-dir", default=".ddgs_venvs", help="Base directory for isolated virtual environments")
    parser.add_argument("--output-dir", default="diagnostic_output", help="Directory for combined reports")
    parser.add_argument("--stages", nargs="+", type=int, default=[1, 2, 3, 4, 5], help="Stages to run (1-5)")
    parser.add_argument("--base-cooldown", type=int, default=2, help="Default seconds between requests")
    parser.add_argument("--max-working-backends", type=int, default=4, help="Max working backends promoted from Stage 1")
    parser.add_argument("--repeats", type=int, default=2, help="Repeated validation runs in Stage 5")
    parser.add_argument("--quick", action="store_true", help="Reduced subset for rapid CI smoke runs")
    parser.add_argument("--reuse-venvs", action="store_true", help="Reuse existing venvs if present")
    parser.add_argument("--gha-groups", action="store_true", help="Emit GitHub Actions collapsible log groups")
    parser.add_argument("--merge-only", metavar="INPUT_DIR", help="Only merge & rank existing raw outputs in INPUT_DIR")

    # Internal flags used when the script invokes itself inside an isolated venv
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-output-dir", default="diagnostic_output/raw", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        return run_worker(args)
    return run_orchestrator(args)


if __name__ == "__main__":
    sys.exit(main())
