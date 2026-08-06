import json
import os
from playwright.sync_api import sync_playwright

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
INPUT_JSON_PATH = "data/reviews/reviews_2026-bhai-tera-star-hai.json"
HTML_DIR = "data/webpages/html_2026-bhai-tera-star-hai"
TARGET_PUBLISHER_ID = "the-times-of-india"

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

def test_toi_extraction():
    print("[STEP 1] Initializing TOI JSON-LD isolated test script.")

    if not os.path.exists(INPUT_JSON_PATH):
        print(f"[ERROR] Input JSON file not found at: {INPUT_JSON_PATH}")
        return

    with open(INPUT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_slug = data.get("movie", {}).get("slug", "unknown_movie")
    publishers = data.get("publishers", [])

    # Find The Times of India entry
    toi_pub = next((p for p in publishers if p.get("publisher_id") == TARGET_PUBLISHER_ID), None)

    if not toi_pub:
        print(f"[ERROR] Publisher ID '{TARGET_PUBLISHER_ID}' not found in JSON.")
        return

    html_file_name = f"webpage_{TARGET_PUBLISHER_ID}_{movie_slug}.html"
    html_file_path = os.path.join(HTML_DIR, html_file_name)

    if not os.path.exists(html_file_path):
        print(f"[ERROR] HTML file missing on disk: {html_file_path}")
        return

    print(f"\n[STEP 2] Launching browser to parse: {html_file_name}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        file_url = f"file://{os.path.abspath(html_file_path)}"
        page.goto(file_url, wait_until="domcontentloaded")

        extracted_data = page.evaluate(JS_EXTRACTOR)
        browser.close()

    print("\n--- EXTRACTION RESULTS FOR THE TIMES OF INDIA ---")
    if "error" in extracted_data:
        print(f"Status: {extracted_data['error']}")
        print("critic_name: could not find from jsonld")
        print("star_rating: could not find from jsonld")
    else:
        critic_names = list(set(extracted_data.get("critic_names", [])))
        star_ratings = list(set(extracted_data.get("star_ratings", [])))

        critic = critic_names[0] if critic_names else "could not find from jsonld"
        rating = star_ratings[0] if star_ratings else "could not find from jsonld"

        print(f"critic_name: {critic}")
        print(f"star_rating: {rating}")
        print(f"Raw found lists -> Critics: {critic_names}, Ratings: {star_ratings}")
    print("-------------------------------------------------")

if __name__ == "__main__":
    test_toi_extraction()
