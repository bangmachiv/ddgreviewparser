#!/usr/bin/env python3

import os
import json
import urllib.request
import urllib.error
import sys

# Force unbuffered stdout for real-time streaming in GitHub Actions
sys.stdout.reconfigure(line_buffering=True)

def main():
    api_key = os.environ.get("SERPER_API_KEY") or os.environ.get("serper_api_key")
    if not api_key:
        print("[FATAL] SERPER_API_KEY environment variable is missing.")
        sys.exit(1)

    # REMOVED double quotes to bypass Serper free tier restrictions
    query = 'Bhai Tera Star Hai 2026 movie review'
    
    print("=" * 80)
    print(" SERPER.DEV RAW 100-RESULT DUMP")
    print(f" Query: {query}")
    print("=" * 80 + "\n")

    url = "https://google.serper.dev/search"
    payload = json.dumps({
        "q": query, 
        "gl": "in",      # India targeting
        "hl": "en",      # English
        "num": 100       # Request max results
    }).encode('utf-8')
    
    headers = {
        'X-API-KEY': api_key, 
        'Content-Type': 'application/json'
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method='POST')

    print(f"[API CALL] Contacting Serper.dev...")
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            organic_results = data.get("organic", [])
            
            print(f"[SUCCESS] Retrieved {len(organic_results)} organic results.\n")
            print("-" * 80)
            
            for item in organic_results:
                # Fallback to enumerating if the API doesn't provide a position key
                rank = item.get("position", 0) 
                title = item.get("title", "No Title")
                link = item.get("link", "No Link")
                
                print(f"#{rank:02d} | {title}")
                print(f"      {link}\n")
                
    except urllib.error.HTTPError as e:
        print(f"[ERROR] API HTTP Error: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"[ERROR] Failed to execute API call: {e}")

if __name__ == "__main__":
    main()
