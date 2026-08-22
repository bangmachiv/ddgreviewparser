#!/usr/bin/env python3

import os
from serpapi import GoogleSearch

def main():
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        print("[FATAL] SERPAPI_API_KEY environment variable is missing.")
        return

    query = "Bhai Tera Star Hai movie review"
    
    print("=" * 80)
    print(" DIAGNOSTIC TEST: SERPAPI INTEGRATION")
    print(f" Target Query : {query}")
    print("=" * 80)

    params = {
        "engine": "google",
        "q": query,
        "api_key": api_key,
        "num": 100,  # Requesting up to 100 results
        "gl": "in",   # Localized to India
        "hl": "en"
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        
        if "error" in results:
            print(f"[API ERROR] {results['error']}")
            return

        organic_results = results.get("organic_results", [])
        print(f"\n[SUMMARY] Successfully fetched {len(organic_results)} organic results from Google via SerpApi.\n")

        for idx, item in enumerate(organic_results, start=1):
            title = item.get("title", "No Title")
            link = item.get("link", "No Link")
            snippet = item.get("snippet", "No Snippet")
            
            print(f"  {idx}. Title: {title}")
            print(f"     URL  : {link}")
            print(f"     Text : {snippet}\n")

    except Exception as e:
        print(f"[FATAL EXCEPTION] {e}")

if __name__ == "__main__":
    main()
