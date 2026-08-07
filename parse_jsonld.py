#!/usr/bin/env python3

import json
import os
import sys
from playwright.sync_api import sync_playwright

# -----------------------------------------------------------------------------
# Configuration & CLI Parsing
# -----------------------------------------------------------------------------
if len(sys.argv) < 2:
    print("[ERROR] Please provide the review JSON path.")
    print("Usage: python extract_jsonld.py data/reviews/2026-bhai-tera-star-hai.json")
    sys.exit(1)

INPUT_JSON_PATH = sys.argv[1]

# JavaScript Extractor: Strictly checks parent-child reviewRating -> ratingValue
JS_EXTRACTOR = """
() => {
    const jsonlds = [...document.querySelectorAll('script[type="application/ld+json"]')]
        .map(s => {
            try {
                return JSON.parse(s.textContent);
            } catch {
                return null;
            }
        })
        .filter(Boolean);

    if (jsonlds.length === 0) {
        return { error: "No JSON-LD found" };
    }

    let results = {
        critic_names: [],
        star_ratings: []
    };

    function search(obj) {
        if (!obj || typeof obj !== "object") return;

        // 1. Check for Author/Critic variants
        ['author', 'reviewer', 'creator'].forEach(key => {
            if (obj[key]) {
                let persons = Array.isArray(obj[key]) ? obj[key] : [obj[key]];
                persons.forEach(p => {
                    if (p && typeof p === "object" && p.name) {
                        results.critic_names.push(p.name);
                    } else if (typeof p === "string") {
                        results.critic_names.push(p);
                    }
                });
            }
        });

        // 2. Strict Parent-Child check for Critic Star Rating
        if (
            obj.reviewRating && 
            typeof obj.reviewRating === "object" && 
            obj.reviewRating.ratingValue !== undefined
        ) {
            results.star_ratings.push(String(obj.reviewRating.ratingValue));
        }

        // Deep recursive search through nested schema trees
        Object.values(obj).forEach(val => {
            if (val && typeof val === "object") {
                search(val);
            }
        });
    }

    jsonlds.forEach(data => search(data));
    return results;
}
"""

def main():
    print(f"[STEP 1] Loading target JSON: {INPUT_JSON_PATH}")

    if not os.path.exists(INPUT_JSON_PATH):
        print(f"[ERROR] Input file not found: {INPUT_JSON_PATH}")
        sys.exit(1)

    with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_slug = data.get("movie", {}).get("slug", "unknown_movie")
    publishers = data.get("publishers", [])

    # Dynamically resolve HTML directory using the movie's slug
    html_dir = f"data/webpages/html_{movie_slug}"

    print(f"[STEP 2] Evaluating local DOMs in folder: {html_dir}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Network blocker: Aborts external HTTP requests for rapid local rendering
        context.route("**/*", lambda route: route.abort() if route.request.url.startswith("http") else route.continue_())

        parsed_count = 0
        skipped_count = 0

        for index, pub in enumerate(publishers, start=1):
            pub_id = pub.get("publisher_id")
            review_url = pub.get("review_url")
            is_download_successful = pub.get("webpage_extraction_successful", pub.get("is_downloaded"))

            print(f"\n--- [{index}/{len(publishers)}] Processing: {pub_id} ---")

            # Skip missing URLs or failed downloads
            if not review_url or review_url == "NA" or str(is_download_successful).upper() != "Y":
                print("[SKIP] Publisher has no valid webpage download (NA).")
                pub["critic_name"] = "Na"
                pub["star_rating"] = "Na"
                pub["json_ld_extraction_status"] = "Na"
                skipped_count += 1
                continue

            # Skip previously resolved entries
            existing_critic = pub.get("critic_name")
            existing_rating = pub.get("star_rating")
            invalid_placeholders = [None, "Na", "NA", "could not find from jsonld"]

            if existing_critic not in invalid_placeholders and existing_rating not in invalid_placeholders:
                print(f"[SKIP] Already parsed: Critic='{existing_critic}', Rating='{existing_rating}'")
                skipped_count += 1
                continue

            # Check primary and fallback HTML paths dynamically
            html_file_path = os.path.join(html_dir, f"webpage_{pub_id}_{movie_slug}.html")
            if not os.path.exists(html_file_path):
                alt_path = os.path.join(html_dir, f"webpage_{pub_id}.html")
                if os.path.exists(alt_path):
                    html_file_path = alt_path
                else:
                    print(f"[WARNING] HTML missing: {html_file_path}")
                    pub["critic_name"] = "could not find from jsonld"
                    pub["star_rating"] = "could not find from jsonld"
                    pub["json_ld_extraction_status"] = "Could not find data from json ld by JS"
                    continue

            try:
                page = context.new_page()
                file_url = f"file://{os.path.abspath(html_file_path)}"
                page.goto(file_url, wait_until="domcontentloaded", timeout=15000)

                extracted_data = page.evaluate(JS_EXTRACTOR)
                page.close()

                if "error" in extracted_data:
                    print(f"  └─► {extracted_data['error']}")
                    pub["critic_name"] = "could not find from jsonld"
                    pub["star_rating"] = "could not find from jsonld"
                    pub["json_ld_extraction_status"] = "Could not find data from json ld by JS"
                else:
                    critic_names = list(dict.fromkeys(extracted_data.get("critic_names", [])))
                    star_ratings = list(dict.fromkeys(extracted_data.get("star_ratings", [])))

                    has_critic = len(critic_names) > 0
                    has_rating = len(star_ratings) > 0

                    pub["critic_name"] = critic_names[0] if has_critic else "could not find from jsonld"
                    pub["star_rating"] = star_ratings[0] if has_rating else "could not find from jsonld"

                    if has_critic and has_rating:
                        pub["json_ld_extraction_status"] = "Found full data from json ld by JS"
                        print(f"  └─► [SUCCESS] Critic: {pub['critic_name']} | Rating: {pub['star_rating']}")
                    elif has_critic or has_rating:
                        pub["json_ld_extraction_status"] = "Found partial data from json ld by JS"
                        print(f"  └─► [PARTIAL] Critic: {pub['critic_name']} | Rating: {pub['star_rating']}")
                    else:
                        pub["json_ld_extraction_status"] = "Could not find data from json ld by JS"
                        print(f"  └─► [NOT FOUND] No matching properties inside JSON-LD blocks.")

                parsed_count += 1

            except Exception as e:
                print(f"[ERROR] Failed parsing {pub_id}: {e}")
                pub["critic_name"] = "could not find from jsonld"
                pub["star_rating"] = "could not find from jsonld"
                pub["json_ld_extraction_status"] = "Could not find data from json ld by JS"

        browser.close()

    # Save directly back to the provided JSON file
    with open(INPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print("\n" + "="*50)
    print("EXTRACTION COMPLETE")
    print(f"Newly parsed files: {parsed_count}")
    print(f"Skipped publishers: {skipped_count}")
    print(f"Updated JSON saved to: {INPUT_JSON_PATH}")
    print("="*50)

if __name__ == "__main__":
    main()
