import json
import os
import glob
import re

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


def process_titles_for_movie(json_path):
    """Reads local HTML files to extract the <title> tag for a single movie file."""
    print("\n" + "="*80)
    print(f" EXTRACTING TITLES FOR LIVE MOVIE FILE: {json_path}")
    print("="*80)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    movie_slug = data.get("movie", {}).get("slug")
    if not movie_slug:
        print(f"[ERROR] Could not find 'slug' inside {json_path}. Skipping.")
        return

    html_dir = f"data/webpages/html_{movie_slug}"
    publishers = data.get("publishers", [])

    # Initialize our summary tracking dictionary
    summary_counts = {
        "Not parsed (already exists)": 0,
        "Not parsed (no url)": 0,
        "Not parsed (no html)": 0,
        "Parsed (fail)": 0,
        "Parsed (success)": 0
    }

    for index, pub in enumerate(publishers, start=1):
        pub_id = pub.get("publisher_id")
        review_url = pub.get("review_url")
        is_download_successful = pub.get("webpage_extraction_successful", pub.get("is_downloaded"))

        # 1. SKIP CHECK: Does the article_title already exist?
        if "article_title" in pub and pub["article_title"] is not None:
            summary_counts["Not parsed (already exists)"] += 1
            continue

        # 2. CHECK PRE-REQUISITES: Url not available
        if not review_url or review_url == "NA":
            pub["article_title"] = None
            summary_counts["Not parsed (no url)"] += 1
            continue

        # 3. CHECK PRE-REQUISITES: Webpage not downloaded
        if str(is_download_successful).upper() != "Y":
            pub["article_title"] = None
            summary_counts["Not parsed (no html)"] += 1
            continue

        # Find the correct HTML file
        html_file_name = f"webpage_{pub_id}_{movie_slug}.html"
        html_file_path = os.path.join(html_dir, html_file_name)

        if not os.path.exists(html_file_path):
            alt_file_path = os.path.join(html_dir, f"webpage_{pub_id}.html")
            if os.path.exists(alt_file_path):
                html_file_path = alt_file_path
            else:
                pub["article_title"] = None
                summary_counts["Not parsed (no html)"] += 1
                continue

        # 4. EXECUTE EXTRACTION
        try:
            # We use errors='ignore' so strange characters don't crash the Python file reader
            with open(html_file_path, "r", encoding="utf-8", errors="ignore") as hf:
                html_content = hf.read()

            # Regex search for the <title> tag, ignoring case and matching across newlines
            match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
            
            if match:
                # Clean up the string by removing extra whitespace or newlines inside the title
                raw_title = match.group(1).strip()
                clean_title = " ".join(raw_title.split())
                
                pub["article_title"] = clean_title
                print(f"  [+] Extracted Title [{pub_id}]: {clean_title}")
                summary_counts["Parsed (success)"] += 1
            else:
                pub["article_title"] = None
                summary_counts["Parsed (fail)"] += 1

        except Exception as e:
            print(f"  [X] Error extracting from {pub_id}: {e}")
            pub["article_title"] = None
            summary_counts["Parsed (fail)"] += 1

    # Save the updated JSON state back to the file
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    # FINAL LOG SUMMARY OUTPUT
    print("-" * 60)
    print(f"SUMMARY FOR: {movie_slug}")
    for category, count in summary_counts.items():
        print(f"{category} : {count}")
    print("=" * 60)


def extract_all_titles():
    print("[STEP 1] Fetching list of LIVE movies for title extraction...")
    live_slugs = get_live_movie_slugs()

    if not live_slugs:
        print("[ERROR] No live movies found in data/movies/. Exiting.")
        return

    print(f"[INFO] Found {len(live_slugs)} live movie(s) to process.")

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

    print("\n[STEP 2] Extracting <title> tags from local HTML files...")
    for json_path in target_files:
        process_titles_for_movie(json_path)

    print("\nALL LIVE MOVIES TITLE EXTRACTION COMPLETE\n")


if __name__ == "__main__":
    extract_all_titles()

