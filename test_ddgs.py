#!/usr/bin/env python3

import logging
import traceback
from ddgs import DDGS

# Enable deep network debugging to see exactly what DuckDuckGo returns
logging.basicConfig(level=logging.DEBUG)

def main():
    query = '"Bhai Tera Star Hai" movie review site:aajtak.in'
    print("="*60)
    print(f" DIAGNOSTIC TEST: DDG SEARCH")
    print(f" Query: {query}")
    print("="*60)
    
    try:
        with DDGS(timeout=30) as ddgs:
            print("\n--- [TEST 1] backend='html' ---")
            try:
                # max_results MUST be a keyword argument in the newest ddgs update
                results_html = list(ddgs.text(query, backend="html", max_results=5))
                print(f"RESULTS FOUND: {len(results_html)}")
                for r in results_html:
                    print(r)
            except Exception:
                print("HTML Backend Exception Caught!")
                traceback.print_exc()
                
            print("\n--- [TEST 2] backend='lite' ---")
            try:
                results_lite = list(ddgs.text(query, backend="lite", max_results=5))
                print(f"RESULTS FOUND: {len(results_lite)}")
                for r in results_lite:
                    print(r)
            except Exception:
                print("Lite Backend Exception Caught!")
                traceback.print_exc()

    except Exception:
        print("DDGS Initialization Failed!")
        traceback.print_exc()

if __name__ == "__main__":
    main()
