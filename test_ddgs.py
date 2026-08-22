#!/usr/bin/env python3

import os
import time
import logging
import traceback
from urllib.parse import urlparse
from ddgs import DDGS

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MAX_RETRIES = 3
RETRY_DELAY = 2
QUERY_COOLDOWN = 1.5  # Polite delay between publisher searches

PUBLISHERS = [
  { "id": "aaj-tak", "name": "Aaj Tak", "url": "https://www.aajtak.in", "category": "text-media-tv-hindi-news", "active": True },
  { "id": "abp", "name": "ABP", "url": "https://www.abplive.com", "category": "text-media-tv-hindi-news", "active": True },
  { "id": "amar-ujala", "name": "Amar Ujala", "url": "https://www.amarujala.com", "category": "text-media-print-hindi-national", "active": True },
  { "id": "bollywood-hungama", "name": "Bollywood Hungama", "url": "https://www.bollywoodhungama.com", "category": "text-media-digital-english-entertainment", "active": True },
  { "id": "bollyspice", "name": "BollySpice", "url": "https://bollyspice.com/", "category": "text-media-digital-english-entertainment", "active": True },
  { "id": "business-standard", "name": "Business Standard", "url": "https://www.business-standard.com", "category": "text-media-print-english-business", "active": True },
  { "id": "cinema-express", "name": "Cinema Express", "url": "https://www.cinemaexpress.com", "category": "text-media-digital-english-entertainment", "active": True },
  { "id": "cinetales", "name": "Cinetales", "url": "https://www.cine-tales.com", "category": "text-media-digital-english-entertainment", "active": True },
  { "id": "dainik-bhaskar", "name": "Dainik Bhaskar", "url": "https://www.bhaskar.com", "category": "text-media-print-hindi-national", "active": True },
  { "id": "dainik-jagran", "name": "Dainik Jagran", "url": "https://www.jagran.com", "category": "text-media-print-hindi-national", "active": True },
  { "id": "deccan-chronicle", "name": "Deccan Chronicle", "url": "https://www.deccanchronicle.com", "category": "text-media-print-english-regional", "active": True },
  { "id": "deccan-herald", "name": "Deccan Herald", "url": "https://www.deccanherald.com", "category": "text-media-print-english-regional", "active": True },
  { "id": "filmfare", "name": "Filmfare", "url": "https://www.filmfare.com", "category": "text-media-print-english-magazine", "active": True },
  { "id": "firstpost", "name": "Firstpost", "url": "https://www.firstpost.com", "category": "text-media-digital-english-news", "active": True },
  { "id": "free-press-journal", "name": "Free Press Journal", "url": "https://www.freepressjournal.in", "category": "text-media-print-english-regional", "active": True },
  { "id": "hindustan", "name": "Hindustan", "url": "https://www.livehindustan.com", "category": "text-media-print-hindi-national", "active": True },
  { "id": "hindustan-times", "name": "Hindustan Times", "url": "https://www.hindustantimes.com", "category": "text-media-print-english-national", "active": True },
  { "id": "ians-live", "name": "IANS Live", "url": "https://ianslive.in", "category": "text-media-digital-english-news", "active": True },
  { "id": "india-today", "name": "India Today", "url": "https://www.indiatoday.in", "category": "text-media-print-english-magazine", "active": True },
  { "id": "koimoi", "name": "Koimoi", "url": "https://www.koimoi.com", "category": "text-media-digital-english-entertainment", "active": True },
  { "id": "lensmen-reviews", "name": "Lensmen Reviews", "url": "https://lensmenreviews.com", "category": "text-media-digital-english-entertainment", "active": True },
  { "id": "lokmat", "name": "Lokmat", "url": "https://www.lokmat.com", "category": "text-media-print-marathi-regional", "active": True },
  { "id": "mid-day", "name": "Mid-Day", "url": "https://www.mid-day.com", "category": "text-media-print-english-regional", "active": True },
  { "id": "mint", "name": "Mint", "url": "https://www.livemint.com", "category": "text-media-print-english-business", "active": True },
  { "id": "moneycontrol", "name": "Moneycontrol", "url": "https://www.moneycontrol.com", "category": "text-media-digital-english-news", "active": True },
  { "id": "movie-talkies", "name": "Movie Talkies", "url": "https://www.movietalkies.com", "category": "text-media-digital-english-entertainment", "active": True },
  { "id": "navbharat-times", "name": "Navbharat Times", "url": "https://navbharattimes.indiatimes.com", "category": "text-media-print-hindi-national", "active": True },
  { "id": "ndtv", "name": "NDTV", "url": "https://www.ndtv.com", "category": "text-media-tv-english-news", "active": True },
  { "id": "news18-showsha", "name": "News18 Showsha", "url": "https://www.news18.com/movies/", "category": "text-media-tv-english-news", "active": True },
  { "id": "outlook", "name": "Outlook", "url": "https://www.outlookindia.com", "category": "text-media-print-english-magazine", "active": True },
  { "id": "peepingmoon", "name": "PeepingMoon", "url": "https://www.peepingmoon.com", "category": "text-media-digital-english-entertainment", "active": True },
  { "id": "rediff", "name": "Rediff.com", "url": "https://www.rediff.com", "category": "text-media-digital-english-news", "active": True },
  { "id": "scroll-in", "name": "Scroll.in", "url": "https://scroll.in", "category": "text-media-digital-english-news", "active": True },
  { "id": "south-asian-herald", "name": "South Asian Herald", "url": "https://southasianherald.com", "category": "text-media-digital-english-news", "active": True },
  { "id": "the-economic-times", "name": "The Economic Times", "url": "https://economictimes.indiatimes.com", "category": "text-media-print-english-business", "active": True },
  { "id": "the-federal", "name": "The Federal", "url": "https://thefederal.com", "category": "text-media-digital-english-news", "active": True },
  { "id": "the-hindu", "name": "The Hindu", "url": "https://www.thehindu.com", "category": "text-media-print-english-national", "active": True },
  { "id": "the-indian-express", "name": "The Indian Express", "url": "https://indianexpress.com", "category": "text-media-print-english-national", "active": True },
  { "id": "the-quint", "name": "The Quint", "url": "https://www.thequint.com", "category": "text-media-digital-english-news", "active": True },
  { "id": "the-telegraph", "name": "The Telegraph", "url": "https://www.telegraphindia.com", "category": "text-media-print-english-national", "active": True },
  { "id": "the-times-of-india", "name": "The Times of India", "url": "https://timesofindia.indiatimes.com", "category": "text-media-print-english-national", "active": True },
  { "id": "the-tribune", "name": "The Tribune", "url": "https://www.tribuneindia.com", "category": "text-media-print-english-regional", "active": True }
]

def extract_domain(url: str) -> str:
    """Extract clean domain name without www."""
    netloc = urlparse(url).netloc
    return netloc.lower().replace("www.", "")

def search_with_retries(ddgs_client, query: str, max_results: int = 5):
    """Executes search using the default 'auto' backend with incremental retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            results = list(
                ddgs_client.text(
                    query,
                    region="in-en",
                    max_results=max_results,
                )
            )
            if results:
                return results, None
        except Exception as exc:
            logging.debug(f"Attempt {attempt} failed for '{query}': {exc}")

        if attempt < MAX_RETRIES:
            time.sleep(attempt * RETRY_DELAY)

    return [], "No results returned after max retries."

def main():
    movie_name = "Bhai Tera Star Hai"
    movie_year = "2026"
    active_publishers = [p for p in PUBLISHERS if p.get("active", True)]

    print("=" * 80)
    print(" DUCKDUCKGO MULTI-PUBLISHER REVIEW DISCOVERY (SPECIFIC -> GENERIC)")
    print(f" Target Movie      : {movie_name} ({movie_year})")
    print(f" Total Publishers  : {len(active_publishers)}")
    print("=" * 80)

    found_summary = []

    with DDGS(timeout=30) as ddgs:
        for idx, pub in enumerate(active_publishers, start=1):
            pub_name = pub["name"]
            domain = extract_domain(pub["url"])

            # INJECTED YEAR INTO QUERIES
            query_specific = f'"{movie_name}" {movie_year} movie review site:{domain}'
            query_generic = f'{movie_name} {movie_year} movie review site:{domain}'

            print(f"\n[{idx}/{len(active_publishers)}] Publisher: {pub_name} ({domain})")

            # 1. First Attempt: Specific (Exact match) Search
            results, err = search_with_retries(ddgs, query_specific, max_results=3)
            search_type = "Specific (Exact)"

            # 2. Second Attempt: Fallback to Generic Search if specific found nothing
            if not results:
                time.sleep(1)
                results, err = search_with_retries(ddgs, query_generic, max_results=3)
                search_type = "Generic (Broad)"

            if results:
                found_summary.append((pub_name, domain, search_type, len(results), results[0].get("href")))
                print(f"  --> MATCH FOUND via [{search_type}]: {len(results)} results")
                for r_idx, item in enumerate(results, start=1):
                    print(f"      {r_idx}. Title: {item.get('title')}")
                    print(f"         URL  : {item.get('href')}")
            else:
                print(f"  --> [x] No results found across specific or generic queries.")

            time.sleep(QUERY_COOLDOWN)

    print("\n" + "=" * 80)
    print(" FINAL EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Total Publishers Queried : {len(active_publishers)}")
    print(f"Publishers With Results  : {len(found_summary)}")
    print("-" * 80)
    for name, domain, stype, count, top_url in found_summary:
        print(f" • {name:<25} [{stype}] -> {top_url}")
    print("=" * 80)

if __name__ == "__main__":
    main()
