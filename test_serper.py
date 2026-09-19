#!/usr/bin/env python3

import os
import time
import json
import urllib.request
import urllib.error
import sys
from urllib.parse import urlparse

# Force unbuffered stdout for real-time streaming in GitHub Actions
sys.stdout.reconfigure(line_buffering=True)

PUBLISHERS = [
  { "id": "aaj-tak", "name": "Aaj Tak", "url": "https://www.aajtak.in", "active": True },
  { "id": "abp", "name": "ABP", "url": "https://www.abplive.com", "active": True },
  { "id": "amar-ujala", "name": "Amar Ujala", "url": "https://www.amarujala.com", "active": True },
  { "id": "bollywood-hungama", "name": "Bollywood Hungama", "url": "https://www.bollywoodhungama.com", "active": True },
  { "id": "bollyspice", "name": "BollySpice", "url": "https://bollyspice.com/", "active": True },
  { "id": "business-standard", "name": "Business Standard", "url": "https://www.business-standard.com", "active": True },
  { "id": "cinema-express", "name": "Cinema Express", "url": "https://www.cinemaexpress.com", "active": True },
  { "id": "cinetales", "name": "Cinetales", "url": "https://www.cine-tales.com", "active": True },
  { "id": "dainik-bhaskar", "name": "Dainik Bhaskar", "url": "https://www.bhaskar.com", "active": True },
  { "id": "dainik-jagran", "name": "Dainik Jagran", "url": "https://www.jagran.com", "active": True },
  { "id": "deccan-chronicle", "name": "Deccan Chronicle", "url": "https://www.deccanchronicle.com", "active": True },
  { "id": "deccan-herald", "name": "Deccan Herald", "url": "https://www.deccanherald.com", "active": True },
  { "id": "filmfare", "name": "Filmfare", "url": "https://www.filmfare.com", "active": True },
  { "id": "firstpost", "name": "Firstpost", "url": "https://www.firstpost.com", "active": True },
  { "id": "free-press-journal", "name": "Free Press Journal", "url": "https://www.freepressjournal.in", "active": True },
  { "id": "hindustan", "name": "Hindustan", "url": "https://www.livehindustan.com", "active": True },
  { "id": "hindustan-times", "name": "Hindustan Times", "url": "https://www.hindustantimes.com", "active": True },
  { "id": "ians-live", "name": "IANS Live", "url": "https://ianslive.in", "active": True },
  { "id": "india-today", "name": "India Today", "url": "https://www.indiatoday.in", "active": True },
  { "id": "koimoi", "name": "Koimoi", "url": "https://www.koimoi.com", "active": True },
  { "id": "lensmen-reviews", "name": "Lensmen Reviews", "url": "https://lensmenreviews.com", "active": True },
  { "id": "lokmat", "name": "Lokmat", "url": "https://www.lokmat.com", "active": True },
  { "id": "mid-day", "name": "Mid-Day", "url": "https://www.mid-day.com", "active": True },
  { "id": "mint", "name": "Mint", "url": "https://www.livemint.com", "active": True },
  { "id": "moneycontrol", "name": "Moneycontrol", "url": "https://www.moneycontrol.com", "active": True },
  { "id": "movie-talkies", "name": "Movie Talkies", "url": "https://www.movietalkies.com", "active": True },
  { "id": "navbharat-times", "name": "Navbharat Times", "url": "https://navbharattimes.indiatimes.com", "active": True },
  { "id": "ndtv", "name": "NDTV", "url": "https://www.ndtv.com", "active": True },
  { "id": "news18-showsha", "name": "News18 Showsha", "url": "https://www.news18.com/movies/", "active": True },
  { "id": "outlook", "name": "Outlook", "url": "https://www.outlookindia.com", "active": True },
  { "id": "peepingmoon", "name": "PeepingMoon", "url": "https://www.peepingmoon.com", "active": True },
  { "id": "rediff", "name": "Rediff.com", "url": "https://www.rediff.com", "active": True },
  { "id": "scroll-in", "name": "Scroll.in", "url": "https://scroll.in", "active": True },
  { "id": "south-asian-herald", "name": "South Asian Herald", "url": "https://southasianherald.com", "active": True },
  { "id": "the-economic-times", "name": "The Economic Times", "url": "https://economictimes.indiatimes.com", "active": True },
  { "id": "the-federal", "name": "The Federal", "url": "https://thefederal.com", "active": True },
  { "id": "the-hindu", "name": "The Hindu", "url": "https://www.thehindu.com", "active": True },
  { "id": "the-indian-express", "name": "The Indian Express", "url": "https://indianexpress.com", "active": True },
  { "id": "the-quint", "name": "The Quint", "url": "https://www.thequint.com", "active": True },
  { "id": "the-telegraph", "name": "The Telegraph", "url": "https://www.telegraphindia.com", "active": True },
  { "id": "the-times-of-india", "name": "The Times of India", "url": "https://timesofindia.indiatimes.com", "active": True },
  { "id": "the-tribune", "name": "The Tribune", "url": "https://www.tribuneindia.com", "active": True }
]

def extract_domain(url: str) -> str:
    """Extract clean domain name without www."""
    netloc = urlparse(url).netloc
    return netloc.lower().replace("www.", "")

def fetch_top_100_reviews(api_key: str, query: str):
    """Fires a SINGLE query to Serper.dev and gets 100 results using standard urllib."""
    url = "https://google.serper.dev/search"
    payload = json.dumps({
        "q": query,
        "gl": "in",      # India targeting
        "hl": "en",      # English
        "num": 100       # Top 100 hits
    }).encode('utf-8')
    
    headers = {
        'X-API-KEY': api_key,
        'Content-Type': 'application/json'
    }

    print(f"[API CALL] Contacting Serper.dev for top 100 results...")
    req = urllib.request.Request(url, data=payload, headers=headers, method='POST')

    start_time = time.time()
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            elapsed = time.time() - start_time
            print(f"[SUCCESS] Received API response in {elapsed:.2f} seconds.")
            return data.get("organic", [])
    except urllib.error.HTTPError as e:
        print(f"[ERROR] API HTTP Error: {e.code} - {e.read().decode('utf-8')}")
        return []
    except Exception as e:
        print(f"[ERROR] Failed to execute API call: {e}")
        return []

def main():
    movie_name = "Bhai Tera Star Hai"
    movie_year = "2026"
    
    # Safely pull from env regardless of casing
    api_key = os.environ.get("SERPER_API_KEY") or os.environ.get("serper_api_key")
    if not api_key:
        print("[FATAL] SERPER_API_KEY environment variable is missing.")
        sys.exit(1)

    active_publishers = [p for p in PUBLISHERS if p.get("active", True)]

    print("=" * 80)
    print(" SERPER REVERSE-MAP DISCOVERY (100-RESULT NET)")
    print(f" Target Movie      : {movie_name} ({movie_year})")
    print(f" Total Publishers  : {len(active_publishers)}")
    print("=" * 80)

    # 1. Fire the single broad shot
    broad_query = f'"{movie_name}" {movie_year} movie review'
    print(f"\n[QUERY] {broad_query}")
    
    top_100_results = fetch_top_100_reviews(api_key, broad_query)
    
    if not top_100_results:
        print("\n[FAILED] No results returned from API.")
        return

    # 2. Build local buckets & lookup map
    publisher_buckets = {pub["id"]: [] for pub in active_publishers}
    domain_to_pub_id = {extract_domain(pub["url"]): pub["id"] for pub in active_publishers}

    # 3. Sort the 100 results into the 42 buckets locally
    print(f"\n[MAPPING] Scanning {len(top_100_results)} organic results against our {len(active_publishers)} publishers...\n")
    
    total_matches = 0
    for rank, result in enumerate(top_100_results, start=1):
        url = result.get("link", "")
        title = result.get("title", "")
        domain = extract_domain(url)
        
        # Reverse map match
        if domain in domain_to_pub_id:
            pub_id = domain_to_pub_id[domain]
            publisher_buckets[pub_id].append({
                "rank": rank,
                "title": title,
                "url": url
            })
            total_matches += 1
            print(f"  --> MATCH [Rank {rank:02d}]: {domain}")

    # 4. Print summary dashboard
    print("\n" + "=" * 80)
    print(" FINAL EXECUTION SUMMARY")
    print("=" * 80)
    
    pubs_with_hits = 0
    for pub in active_publishers:
        hits = publisher_buckets[pub["id"]]
        if hits:
            pubs_with_hits += 1
            print(f" • {pub['name']:<25} | {len(hits)} results | Best Rank: #{hits[0]['rank']}")
            for h in hits:
                print(f"      - {h['title']}")
                print(f"        {h['url']}")
    
    print("-" * 80)
    print(f"Total Organic Links Mapped : {total_matches}")
    print(f"Total Publishers Found     : {pubs_with_hits} out of {len(active_publishers)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
