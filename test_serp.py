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

def extract_domain(url):
    netloc = urlparse(url).netloc
    return netloc.lower().replace("www.", "")

def main():
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("[FATAL] TAVILY_API_KEY environment variable is missing.")
        return

    client = TavilyClient(api_key=api_key)
    
    # 1. Broad search query prioritizing the movie name, year, and intent
    query = "Bhai Tera Star Hai 2026 movie review"

    # 2. Build a map of our active publisher domains
    # Maps e.g., "ndtv.com" -> { publisher dict }
    publisher_map = {extract_domain(p["url"]): p for p in PUBLISHERS if p["active"]}
    
    # Dictionaries to hold categorized results
    matched_results = {p["id"]: [] for p in PUBLISHERS if p["active"]}
    unmatched_results = []

    print("=" * 80)
    print(" DIAGNOSTIC TEST: TAVILY API (BROAD SEARCH & LOCAL FILTERING)")
    print(f" Target Query : {query}")
    print(f" Tracking     : {len(publisher_map)} active publishers")
    print("=" * 80)

    try:
        # 3. Fire the broad search.
        # Requesting max_results=100 tells Tavily to return its absolute maximum limit.
        response = client.search(
            query=query,
            search_depth="advanced",
            max_results=100
        )

        results = response.get("results", [])
        print(f"-> Tavily returned a total of {len(results)} results.\n")

        # 4. Filter & categorize the results locally in Python
        for item in results:
            item_url = item.get("url", "")
            item_domain = extract_domain(item_url)
            
            # Check if this item's domain perfectly matches OR ends with any of our publisher domains 
            # (This catches subdomains like "movies.ndtv.com" pointing back to "ndtv.com")
            matched_pub_id = None
            for pub_domain, pub_data in publisher_map.items():
                if item_domain == pub_domain or item_domain.endswith("." + pub_domain):
                    matched_pub_id = pub_data["id"]
                    break
            
            if matched_pub_id:
                matched_results[matched_pub_id].append(item)
            else:
                unmatched_results.append(item)

        # 5. Print results publisher by publisher
        print("=" * 80)
        print(" MATCHED PUBLISHER RESULTS ")
        print("=" * 80)
        
        matches_found = 0
        for pub_id, pub_items in matched_results.items():
            if pub_items:
                matches_found += len(pub_items)
                pub_name = next(p["name"] for p in PUBLISHERS if p["id"] == pub_id)
                print(f"\n--- {pub_name} ({pub_id}) [{len(pub_items)} result(s)] ---")
                for r_idx, item in enumerate(pub_items, start=1):
                    print(f"  {r_idx}. Title: {item.get('title')}")
                    print(f"     URL  : {item.get('url')}")
                    print(f"     Score: {item.get('score')}")

        if matches_found == 0:
            print("\n  [!] No matches found for any of the tracked publishers.")

        # 6. Print the unmatched results
        print("\n" + "=" * 80)
        print(f" UNMATCHED RESULTS (Not in tracked publishers) [{len(unmatched_results)} result(s)]")
        print("=" * 80)
        
        for r_idx, item in enumerate(unmatched_results, start=1):
            print(f"\n  {r_idx}. Domain: {extract_domain(item.get('url'))}")
            print(f"     Title : {item.get('title')}")
            print(f"     URL   : {item.get('url')}")
            print(f"     Score : {item.get('score')}")

        print(f"\n" + "=" * 80)
        print(f" SUMMARY: Total {len(results)} | Matched: {matches_found} | Unmatched: {len(unmatched_results)}")
        print("=" * 80)

    except Exception as e:
        print(f"\n[ERROR executing Tavily search]: {e}")

if __name__ == "__main__":
    main()
