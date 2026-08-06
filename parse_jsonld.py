import json
import os
from playwright.sync_api import sync_playwright

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "data/reviews/reviews_2026-bhai-tera-star-hai.json"
HTML_DIR = "data/webpages/html_2026-bhai-tera-star-hai"

# The exact JavaScript extraction logic you tested in Chrome
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

        // Check author.name
        if (obj.author) {
            let authors = Array.isArray(obj.author) ? obj.author : [obj.author];
            authors.forEach(a => {
                if (a && typeof a === "object" && a.name) {
                    results.critic_names.push(a.name);
                }
            });
        }

        // Check reviewRating.ratingValue
        if (
            obj.reviewRating &&
            typeof obj.reviewRating === "object" &&
            obj.reviewRating.ratingValue !== undefined
        ) {
            results.star_ratings.push(obj.reviewRating.ratingValue);
        }

        // Continue recursion
        Object.keys(obj).forEach(key => {
            search(obj[key]);
        });
    }

    jsonlds.forEach(data => {
        search(data);
    });

    return results;
}
"""

def parse_all_htmls():
    print("[STEP 1] Initializing full batch JSON-LD parser script.")

    if not os.path.exists(INPUT_JSON_PATH):
        print(f"[ERROR] Input JSON file not found at: {INPUT_JSON_PATH}")
        return

    with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_slug = data.get("movie", {}).get("slug", "unknown_movie")
    publishers = data.get("publishers", [])

    print("\n[STEP 2] Launching headless browser for local DOM evaluation...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        parsed_count = 0
        skipped_count = 0

        for index, pub in enumerate(publishers, start=1):
            pub_id = pub.get("publisher_id")
            review_url = pub.get("review_url")
            is_download_successful = pub.get("webpage_extraction_successful")

            print(f"\n--- [{index}/{len(publishers)}] Processing: {pub_id} ---")

            # 1. If URL is NA, set Na status and skip
            if not review_url or review_url == "NA" or str(is_download_successful).upper() != "Y":
                print("[SKIP] Publisher has no valid webpage download (NA).")
                pub["critic_name"] = "Na"
                pub["star_rating"] = "Na"
                pub["json_ld_extraction_status"] = "Na"
                skipped_count += 1
                continue

            # 2. Smart optimization: Skip if both fields already exist and contain valid extracted data
            existing_critic = pub.get("critic_name")
            existing_rating = pub.get("star_rating")
            
            invalid_placeholders = [None, "Na", "NA", "could not find from jsonld"]
            if existing_critic not in invalid_placeholders and existing_rating not in invalid_placeholders:
                print(f"[SKIP] Both critic and rating already successfully parsed: Critic='{existing_critic}', Rating='{existing_rating}'")
                skipped_count += 1
                continue

            html_file_name = f"webpage_{pub_id}_{movie_slug}.html"
            html_file_path = os.path.join(HTML_DIR, html_file_name)

            if not os.path.exists(html_file_path):
                print(f"[WARNING] HTML file missing on disk for: {pub_id}")
                pub["critic_name"] = "could not find from jsonld"
                pub["star_rating"] = "could not find from jsonld"
                pub["json_ld_extraction_status"] = "Could not find data from json ld by JS"
                continue

            try:
                page = context.new_page()
                file_url = f"file://{os.path.abspath(html_file_path)}"
                page.goto(file_url, wait_until="domcontentloaded")

                extracted_data = page.evaluate(JS_EXTRACTOR)
                page.close()

                if "error" in extracted_data:
                    print(f"  └─► {extracted_data['error']}")
                    pub["critic_name"] = "could not find from jsonld"
                    pub["star_rating"] = "could not find from jsonld"
                    pub["json_ld_extraction_status"] = "Could not find data from json ld by JS"
                else:
                    critic_names = list(set(extracted_data.get("critic_names", [])))
                    star_ratings = list(set(extracted_data.get("star_ratings", [])))

                    has_critic = len(critic_names) > 0
                    has_rating = len(star_ratings) > 0

                    pub["critic_name"] = critic_names[0] if has_critic else "could not find from jsonld"
                    pub["star_rating"] = star_ratings[0] if has_rating else "could not find from jsonld"

                    # Determine specific status flag
                    if has_critic and has_rating:
                        pub["json_ld_extraction_status"] = "Found full data from json ld by JS"
                        print(f"  └─► [SUCCESS] Found Critic: {pub['critic_name']} | Rating: {pub['star_rating']}")
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

    # Save updated JSON state back to file
    with open(INPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print("\n" + "="*40)
    print("JSON-LD BATCH PARSING COMPLETE")
    print(f"Newly parsed files: {parsed_count}")
    print(f"Skipped publishers: {skipped_count}")
    print(f"Updated JSON saved back to: {INPUT_JSON_PATH}")
    print("="*40)

if __name__ == "__main__":
    parse_all_htmls()
