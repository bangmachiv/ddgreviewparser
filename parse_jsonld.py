import json
import os
import glob
from playwright.sync_api import sync_playwright

# STRICT JavaScript extraction logic
# Enforces the parent-child relationship: obj.reviewRating.ratingValue
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

        // 1. Look for Author/Critic variants (author, reviewer, creator)
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

        // 2. STRICT Parent-Child Check: reviewRating -> ratingValue
        if (
            obj.reviewRating && 
            typeof obj.reviewRating === "object" && 
            obj.reviewRating.ratingValue !== undefined
        ) {
            results.star_ratings.push(String(obj.reviewRating.ratingValue));
        }

        // Keep digging recursively through the object
        Object.values(obj).forEach(val => {
            if (val && typeof val === "object") {
                search(val);
            }
        });
    }

    jsonlds.forEach(data => {
        search(data);
    });

    return results;
}
"""

def get_live_movie_slugs():
    """Reads the data/movies/ folder to find exactly which movies are LIVE today."""
    slugs = []
    live_master_file = "data/movies/movies-live-today.json"

    if os.path.exists(live_master_file):
        print(f"[INFO] Reading live movies from master file: {live_master_file}")
        with open(live_master_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            movie_list = data if isinstance(data, list) else data.get("movies", [])
            for movie in movie_list:
                if isinstance(movie, dict) and "slug" in movie:
                    slugs.append(movie["slug"])
    else:
        print(f"[INFO] {live_master_file} not found. Scanning individual files in data/movies/...")
        for file_path in glob.glob("data/movies/*.json"):
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    slug = data.get("slug") or data.get("movie", {}).get("slug")
                    if slug:
                        slugs.append(slug)
                except Exception as e:
                    print(f"[WARNING] Could not read slug from {file_path}: {e}")

    return list(set(slugs))


def process_single_movie_json(json_path, context):
    """Parses local HTML files and extracts JSON-LD for a single movie file."""
    print("\n" + "="*60)
    print(f" PROCESSING LIVE MOVIE FILE: {json_path}")
    print("="*60)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_slug = data.get("movie", {}).get("slug")
    if not movie_slug:
        print(f"[ERROR] Could not find 'slug' inside {json_path}. Skipping.")
        return

    html_dir = f"data/webpages/html_{movie_slug}"
    publishers = data.get("publishers", [])

    if not os.path.exists(html_dir):
        print(f"[WARNING] HTML directory not found at: {html_dir}. Skipping.")
        return

    parsed_count = 0
    skipped_count = 0
    
    # Dictionary to track our final summary logs based on the new rigorous rules
    summary_counts = {
        "Skipped (URL missing)": 0,
        "Skipped (Webpage missing)": 0,
        "Skipped (Already successfully parsed)": 0,
        "no data found": 0,
        "one data found (critic name)": 0,
        "one data found (star rating)": 0,
        "both data found": 0,
        "Error during parsing": 0
    }

    for index, pub in enumerate(publishers, start=1):
        pub_id = pub.get("publisher_id")
        review_url = pub.get("review_url")
        is_download_successful = pub.get("webpage_extraction_successful", pub.get("is_downloaded"))

        print(f"\n--- [{index}/{len(publishers)}] Processing: {pub_id} ---")

        # 1. SKIP CHECK: If we already have one of the 4 valid statuses, skip entirely
        current_status = str(pub.get("json_ld_extraction_status", "")).strip()
        
        valid_statuses = [
            "no data found",
            "both data found",
            "one data found (star rating)",
            "one data found (critic name)"
        ]

        if current_status in valid_statuses:
            print(f"  └─► Skipped (Already parsed: '{current_status}')")
            summary_counts["Skipped (Already successfully parsed)"] += 1
            skipped_count += 1
            continue

        # 2. CHECK PRE-REQUISITES: URL not available -> Do NOT modify pub, just skip
        if not review_url or review_url == "NA":
            print("  └─► Skipped (URL missing)")
            summary_counts["Skipped (URL missing)"] += 1
            skipped_count += 1
            continue

        # 3. CHECK PRE-REQUISITES: Webpage not downloaded -> Do NOT modify pub, just skip
        if str(is_download_successful).upper() != "Y":
            print("  └─► Skipped (Webpage missing)")
            summary_counts["Skipped (Webpage missing)"] += 1
            skipped_count += 1
            continue

        # 4. VERIFY HTML EXISTS ON DISK -> Do NOT modify pub, just skip if absent
        html_file_name = f"webpage_{pub_id}_{movie_slug}.html"
        html_file_path = os.path.join(html_dir, html_file_name)

        if not os.path.exists(html_file_path):
            alt_file_path = os.path.join(html_dir, f"webpage_{pub_id}.html")
            if os.path.exists(alt_file_path):
                html_file_path = alt_file_path
            else:
                print("  └─► Skipped (HTML file not found on disk)")
                summary_counts["Skipped (Webpage missing)"] += 1
                skipped_count += 1
                continue

        # 5. EXECUTE HTML PARSING VIA PLAYWRIGHT
        try:
            page = context.new_page()
            file_url = f"file://{os.path.abspath(html_file_path)}"
            
            page.goto(file_url, wait_until="domcontentloaded", timeout=15000)
            extracted_data = page.evaluate(JS_EXTRACTOR)
            page.close()

            if "error" in extracted_data:
                status_msg = "no data found"
                pub["critic_name"] = "could not find from jsonld"
                pub["star_rating"] = "could not find from jsonld"
                pub["json_ld_extraction_status"] = status_msg
                print(f"  └─► {status_msg}")
                summary_counts[status_msg] += 1
            else:
                critic_names = list(dict.fromkeys(extracted_data.get("critic_names", [])))
                star_ratings = list(dict.fromkeys(extracted_data.get("star_ratings", [])))

                has_critic = len(critic_names) > 0
                has_rating = len(star_ratings) > 0

                # Assign extracted values or default empty state
                pub["critic_name"] = critic_names[0] if has_critic else "could not find from jsonld"
                pub["star_rating"] = star_ratings[0] if has_rating else "could not find from jsonld"

                # Assign strict status based on analysis
                if has_critic and has_rating:
                    status_msg = "both data found"
                elif has_rating and not has_critic:
                    status_msg = "one data found (star rating)"
                elif has_critic and not has_rating:
                    status_msg = "one data found (critic name)"
                else:
                    status_msg = "no data found"

                pub["json_ld_extraction_status"] = status_msg
                print(f"  └─► {status_msg}")
                summary_counts[status_msg] += 1

            parsed_count += 1

        except Exception as e:
            # If Playwright crashes, do NOT modify pub so it can retry later
            print(f"  └─► Error during parsing: {e}")
            summary_counts["Error during parsing"] += 1
            skipped_count += 1

    # Save updated JSON state back to the exact target file
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    # FINAL LOG SUMMARY OUTPUT
    print(f"\n[{movie_slug}] PARSING COMPLETE -> Parsed: {parsed_count} | Skipped: {skipped_count}")
    print("-" * 60)
    for category, count in summary_counts.items():
        if count > 0:
            print(f"{category} : {count}")
    print("=" * 60)


def parse_all_live_movies():
    print("[STEP 1] Fetching list of LIVE movies...")
    live_slugs = get_live_movie_slugs()

    if not live_slugs:
        print("[ERROR] No live movies found in data/movies/. Exiting.")
        return

    print(f"[INFO] Found {len(live_slugs)} live movie(s) to process: {', '.join(live_slugs)}")

    target_files = []
    for slug in live_slugs:
        review_file = f"data/reviews/reviews_{slug}.json"
        if os.path.exists(review_file):
            target_files.append(review_file)
        else:
            print(f"[WARNING] Review file missing for live movie: {review_file}")

    if not target_files:
        print("[ERROR] None of the live movies have corresponding review JSON files. Exiting.")
        return

    print("\n[STEP 2] Launching headless browser for JSON-LD Evaluation...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Block external network requests to keep loading instant
        context.route("**/*", lambda route: route.abort() if route.request.url.startswith("http") else route.continue_())

        for json_path in target_files:
            process_single_movie_json(json_path, context)

        browser.close()

    print("\n" + "="*40)
    print("ALL LIVE MOVIES JSON-LD PARSING COMPLETE")
    print("="*40)


if __name__ == "__main__":
    parse_all_live_movies()
