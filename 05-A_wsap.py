#!/usr/bin/env python3
"""
05-A_wsap.py
Generates a WhatsApp-formatted summary of movie reviews.
Reads from the finalized reviews JSON schema.
Cascades: 
  - Rating: jsonld_star_rating -> ai_star_rating -> ai_sentiment_category (Unrated)
  - Critic: jsonld_critic_name -> ai_critic_name -> Blank
Appends execution metrics to a structured JSON log file.
"""

import json
import sys
import os
import re
import math
import traceback
from datetime import datetime

def parse_rating(val):
    bad_values = [None, "", "Na", "NA", "null", "FAILED", "PENDING", "NOT_NEEDED"]
    if val in bad_values or "could not find" in str(val).lower():
        return None
    try:
        return float(val)
    except ValueError:
        return None

def parse_critic(val):
    bad_values = [None, "", "Na", "NA", "null", "FAILED", "PENDING", "NOT_NEEDED"]
    if val in bad_values or str(val).strip().upper() in bad_values:
        return ""
    return str(val).strip()

def format_subgroup_rating(rating):
    if rating == 0:
        return "☆☆☆☆☆"
    if rating == 0.5:
        return "½"

    full = int(rating)
    half = (rating - full) >= 0.5

    stars = "★" * full
    if half:
        stars += "½"
    return stars

def generate_whatsapp_message(data):
    # --- Data Extraction ---
    movie = data.get("movie", {})
    movie_name = str(movie.get("name", "Unknown Movie")).strip()
    movie_slug = str(movie.get("slug", "unknown_slug")).strip()

    # Extract Year
    date_str = str(movie.get("date", "")).strip()
    year = date_str[:4] if len(date_str) >= 4 else "YYYY"

    valid_reviews = []
    rated_count = 0
    total_rating_sum = 0.0

    # --- Tracking Lists for End-of-Run Logs ---
    ai_slotted_pubs = []
    missing_highlight_pubs = []

    for pub in data.get("publishers", []):
        url = pub.get("review_url")
        raw_title = pub.get("clean_title")
        
        # Checking both potential keys for safety based on legacy schema vs new
        highlighted_title = pub.get("highlighted_title", pub.get("clean_highlighted_title"))  
        ai_cat = str(pub.get("ai_sentiment_category", "")).strip().upper()

        # Normalize Publisher Name
        pub_name = str(pub.get("publisher_name", "")).strip()
        pub_name = re.sub(r'\s*\.\s*', ' . ', pub_name)

        # Exclude invalid reviews
        if not url or str(url).strip().upper() == "NA":
            continue
        if not raw_title or str(raw_title).strip().upper() in ["PENDING", "FAILED", ""]:
            continue

        # Logging Missing Highlights
        if not highlighted_title or str(highlighted_title).strip().upper() in ["PENDING", "FAILED", ""]:
            missing_highlight_pubs.append(pub_name)
            display_title = str(raw_title).strip()
        else:
            # Convert *word* to _word_ to use WhatsApp italics instead of bold
            display_title = re.sub(r'\*(.*?)\*', r'_\1_', str(highlighted_title).strip())

        # --- CASCADING LOGIC: Critic Name ---
        ld_critic = parse_critic(pub.get("jsonld_critic_name"))
        ai_critic = parse_critic(pub.get("ai_critic_name"))
        
        final_critic = ld_critic if ld_critic else ai_critic

        # --- CASCADING LOGIC: Star Rating ---
        ld_rating = parse_rating(pub.get("jsonld_star_rating"))
        ai_rating = parse_rating(pub.get("ai_star_rating"))
        
        final_rating = ld_rating if ld_rating is not None else ai_rating

        # --- EXCLUSION RULE ---
        # If no numerical rating AND no AI fallback label, skip entirely
        if final_rating is None and ai_cat not in ["GOOD", "NEUTRAL", "BAD", "POSITIVE", "MIXED", "NEGATIVE"]:
            continue

        # Category Assignment Logic
        if final_rating is not None:
            rated_count += 1
            total_rating_sum += final_rating
            if final_rating >= 4:
                cat = "GOOD"
            elif final_rating >= 3:
                cat = "NEUTRAL"
            else:
                cat = "BAD"
        else:
            # Handle Unrated Reviews using AI Category (Groq Label)
            if ai_cat in ["GOOD", "POSITIVE"]:
                cat = "GOOD"
                ai_slotted_pubs.append(f"{pub_name} -> Slotted as GOOD")
            elif ai_cat in ["NEUTRAL", "MIXED"]:
                cat = "NEUTRAL"
                ai_slotted_pubs.append(f"{pub_name} -> Slotted as NEUTRAL")
            elif ai_cat in ["BAD", "NEGATIVE"]:
                cat = "BAD"
                ai_slotted_pubs.append(f"{pub_name} -> Slotted as BAD")
            else:
                # Failsafe skip
                continue

        valid_reviews.append({
            'title': display_title,
            'publisher': pub_name,
            'critic': final_critic,
            'rating': final_rating,
            'category': cat
        })

    total_reviews = len(valid_reviews)

    # --- Header Math ---
    avg_rating = 0.0
    if rated_count > 0:
        avg_rating = round(total_rating_sum / rated_count, 1)

    if avg_rating >= 4:
        overall_verdict = "GOOD"
    elif avg_rating >= 3:
        overall_verdict = "NEUTRAL"
    else:
        overall_verdict = "BAD"

    # --- Rating Distribution ---
    dist_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0, 0: 0}
    for r in valid_reviews:
        if r['rating'] is not None:
            bucket = math.floor(r['rating'])
            if bucket > 5: bucket = 5
            if bucket < 0: bucket = 0
            dist_counts[bucket] += 1

    def dist_stars(b):
        return ("★" * b) + ("☆" * (5 - b))

    dist_rows = []
    for b in [5, 4, 3, 2, 1]:
        c = dist_counts[b]
        dist_rows.append(f"`{dist_stars(b)}  {c} review{'s' if c != 1 else ''}`")

    if dist_counts[0] > 0:
        c = dist_counts[0]
        dist_rows.append(f"`☆☆☆☆☆  {c} review{'s' if c != 1 else ''}`")

    # --- Message Construction ---
    lines = []

    # 1. HEADER
    lines.append(f"*{movie_name}* ({year})")
    lines.append("")
    lines.append(f"*{avg_rating:.1f}/5 • {overall_verdict}*")
    lines.append(f"{rated_count} ratings · {total_reviews} reviews")
    lines.append("")
    lines.append("*RATING DISTRIBUTION*")
    lines.append("")
    for row in dist_rows:
        lines.append(row)

    # Two blank lines after final distribution row
    lines.extend(["", ""])

    # 2. BODY CATEGORIES
    categories = {"GOOD": [], "NEUTRAL": [], "BAD": []}
    for r in valid_reviews:
        categories[r['category']].append(r)

    for cat_name in ["GOOD", "NEUTRAL", "BAD"]:
        cat_reviews = categories[cat_name]
        cat_count = len(cat_reviews)

        # Category Header
        if cat_name == "GOOD":
            lines.append(f"👍 *Good* • {cat_count} Review{'s' if cat_count != 1 else ''}")
        elif cat_name == "NEUTRAL":
            lines.append(f"🤞 *Neutral* • {cat_count} Review{'s' if cat_count != 1 else ''}")
        else:
            lines.append(f"👎 *Bad* • {cat_count} Review{'s' if cat_count != 1 else ''}")

        lines.append("")

        # Zero Reviews Handle
        if cat_count == 0:
            lines.append("No Reviews")
            lines.extend(["", ""])
            continue

        # Group Subgroups
        rated_groups = {}
        unrated = []
        for r in cat_reviews:
            if r['rating'] is not None:
                if r['rating'] not in rated_groups:
                    rated_groups[r['rating']] = []
                rated_groups[r['rating']].append(r)
            else:
                unrated.append(r)

        # Sort rated subgroups descending
        sorted_ratings = sorted(rated_groups.keys(), reverse=True)

        # Print Rated Subgroups
        for rating in sorted_ratings:
            group = rated_groups[rating]
            c = len(group)
            lines.append(f"*{format_subgroup_rating(rating)}* • {c} Review{'s' if c != 1 else ''}")
            lines.append("")

            for idx, r in enumerate(group):
                lines.append(r['title'])
                
                # Format publisher and critic exactly as requested
                if r['critic']:
                    lines.append(f"`{r['publisher']} | {r['critic']}`")
                else:
                    lines.append(f"`{r['publisher']}`")

                # 1 blank line between reviews
                if idx < len(group) - 1:
                    lines.append("")

            # 2 blank lines after subgroup finishes
            lines.extend(["", ""])

        # Print Unrated Subgroup
        if unrated:
            c = len(unrated)
            lines.append(f"*UNRATED* · {c} Review{'s' if c != 1 else ''}")
            lines.append("")

            for idx, r in enumerate(unrated):
                lines.append(r['title'])
                
                # Format publisher and critic exactly as requested
                if r['critic']:
                    lines.append(f"`{r['publisher']} | {r['critic']}`")
                else:
                    lines.append(f"`{r['publisher']}`")

                # 1 blank line between reviews
                if idx < len(unrated) - 1:
                    lines.append("")

            # 2 blank lines after subgroup finishes
            lines.extend(["", ""])

    return "\n".join(lines).strip(), movie_slug, ai_slotted_pubs, missing_highlight_pubs, total_reviews

def main():
    if len(sys.argv) < 2:
        sys.stderr.write("[ERROR] Missing JSON input path argument.\n")
        sys.stderr.write("Usage: python 05-A_wsap.py <path_to_json>\n")
        sys.exit(1)

    input_path = sys.argv[1]
    sys.stderr.write(f"\n[DEBUG] Starting processing for input file: {input_path}\n")

    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    except Exception as e:
        sys.stderr.write(f"[ERROR] Failed to read or parse input JSON: {str(e)}\n")
        sys.exit(1)

    wsap_msg, slug, ai_slotted_pubs, missing_highlight_pubs, total_reviews = generate_whatsapp_message(json_data)

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # --- File Saving Logic (.txt format) ---
    try:
        out_dir = os.path.join(BASE_DIR, "data", "output", "wsap")
        os.makedirs(out_dir, exist_ok=True)

        out_path = os.path.join(out_dir, f"wsap_{slug}.txt")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(wsap_msg)

        sys.stderr.write(f"[SUCCESS] File successfully written to: {out_path}\n")
    except Exception as e:
        sys.stderr.write(f"[FATAL ERROR] Failed to save output text file!\n")
        sys.stderr.write(f"[EXCEPTION DETAILS]: {str(e)}\n")
        traceback.print_exc(file=sys.stderr)

    # --- Structured JSON Appending Logic ---
    try:
        log_dir = os.path.join(BASE_DIR, "logs", f"logs_{slug}")
        os.makedirs(log_dir, exist_ok=True)
        json_log_path = os.path.join(log_dir, "05-A_output-wsap.json")

        script_log_data = {}
        if os.path.exists(json_log_path) and os.path.getsize(json_log_path) > 0:
            try:
                with open(json_log_path, "r", encoding="utf-8") as lf:
                    script_log_data = json.load(lf)
            except json.JSONDecodeError:
                pass

        # Append new timestamped run entry
        run_entry = {
            "movie_slug": slug,
            "total_reviews_formatted": total_reviews,
            "unrated_ai_slotted_publishers": ai_slotted_pubs,
            "missing_highlight_publishers": missing_highlight_pubs
        }
        
        script_log_data[datetime.now().astimezone().isoformat()] = run_entry

        with open(json_log_path, "w", encoding="utf-8") as lf:
            json.dump(script_log_data, lf, ensure_ascii=False, indent=4)
            
        sys.stderr.write(f"[SUCCESS] Run metrics appended to JSON log: {json_log_path}\n")
    except Exception as e:
        sys.stderr.write(f"[ERROR] Failed to save JSON log file!\n")
        sys.stderr.write(f"[EXCEPTION DETAILS]: {str(e)}\n")

    # --- Print Final Execution Logs (to stderr) ---
    sys.stderr.write("\n======================================================\n")
    sys.stderr.write("               FINAL EXECUTION LOGS\n")
    sys.stderr.write("======================================================\n")

    sys.stderr.write(f"\n[AI CLASSIFICATION STATUS]\n")
    sys.stderr.write(f"Successfully slotted {len(ai_slotted_pubs)} unrated reviews using 'ai_sentiment_category':\n")
    if ai_slotted_pubs:
        for pub in ai_slotted_pubs:
            sys.stderr.write(f"  ✓ {pub}\n")
    else:
        sys.stderr.write("  - None\n")

    sys.stderr.write(f"\n[MISSING HIGHLIGHTS STATUS]\n")
    sys.stderr.write(f"Found {len(missing_highlight_pubs)} publishers with a clean title but NO highlighted title:\n")
    if missing_highlight_pubs:
        for pub in missing_highlight_pubs:
            sys.stderr.write(f"  ⚠ {pub}\n")
    else:
        sys.stderr.write("  - None (All valid titles have highlights!)\n")

    sys.stderr.write("======================================================\n\n")

    # Output strict final WhatsApp message to standard out
    print(wsap_msg)

if __name__ == "__main__":
    main()
