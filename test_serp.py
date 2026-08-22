#!/usr/bin/env python3

import os
from urllib.parse import urlparse
from tavily import TavilyClient

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

EXCLUDE_PUBLISHER_IDS = {
    # Batch 1 Exclusions
    "bollywood-hungama", "cinema-express", "dainik-jagran", "filmfare", "free-press-journal",
    # Batch 2 Exclusions
    "koimoi", "mid-day", "movie-talkies", "india-today", "hindustan-times",
    # Batch 3 Exclusions
    "the-indian-express", "the-times-of-india", "rediff", "scroll-in"
}

def extract_domain(url):
    netloc = urlparse(url).netloc
    return netloc.lower().replace("www.", "")

def main():
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("[FATAL] TAVILY_API_KEY environment variable is missing.")
        return

    client = TavilyClient(api_key=api_key)
    query = "Bhai Tera Star Hai movie review"

    # Step 1: Pair publisher IDs with their clean domains
    domains_with_ids = [(p["id"], extract_domain(p["url"])) for p in PUBLISHERS if p["active"]]
    
    # Step 2: Create the original 15-size batches
    original_batches = [domains_with_ids[i:i + 15] for i in range(0, len(domains_with_ids), 15)]
    
    # Step 3: Strip out the successfully tested domains from each batch
    filtered_batches = []
    for original_batch in original_batches:
        cleaned_batch_domains = [
            domain for pub_id, domain in original_batch 
            if pub_id not in EXCLUDE_PUBLISHER_IDS
        ]
        filtered_batches.append(cleaned_batch_domains)

    print("=" * 80)
    print(" DIAGNOSTIC TEST: TAVILY API (FORCED EXCLUSION BATCHING)")
    print(f" Target Query : {query}")
    print(f" Excluded     : {len(EXCLUDE_PUBLISHER_IDS)} top publishers")
    print("=" * 80)

    total_matches = 0

    for idx, batch_domains in enumerate(filtered_batches, start=1):
        print(f"\n--- Batch {idx} ({len(batch_domains)} domains remaining) ---")
        
        if not batch_domains:
            print("No domains left in this batch to query.")
            continue
            
        try:
            response = client.search(
                query=query,
                search_depth="advanced",
                include_domains=batch_domains,
                max_results=10
            )
            
            results = response.get("results", [])
            total_matches += len(results)
            print(f"Found {len(results)} matches in this batch:\n")

            for r_idx, item in enumerate(results, start=1):
                print(f"  {r_idx}. Title: {item.get('title')}")
                print(f"     URL  : {item.get('url')}")
                print(f"     Score: {item.get('score')}\n")

        except Exception as e:
            print(f"[ERROR in Batch {idx}] {e}")

    print(f"=" * 80)
    print(f" SUMMARY: Total results aggregated across forced exclusion run: {total_matches}")
    print("=" * 80)

if __name__ == "__main__":
    main()
