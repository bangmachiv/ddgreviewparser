import json
import sys
import os
import re
import math
import traceback

def parse_rating(val):
    if val in (None, "", "Na", "NA", "null") or "could not find" in str(val).lower():
        return None
    try:
        return float(val)
    except ValueError:
        return None

def classify_unrated(title):
    t = title.lower()
    bad_phrases = ["pointless", "painful", "fails to impress", "can't save this film",
                   "delivers little", "unfunny", "absurd", "nightmare",
                   "strains patience", "bad", "poor", "disappointing"]
    good_phrases = ["excellent", "brilliant", "outstanding", "terrific",
                    "superb", "delightful", "impressive", "entertaining"]
    
    for b in bad_phrases:
        if b in t: return "BAD"
    for g in good_phrases:
        if g in t: return "GOOD"
    return "NEUTRAL"

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
    
    for pub in data.get("publishers", []):
        url = pub.get("review_url")
        raw_title = pub.get("clean_title")
        highlighted_title = pub.get("clean_highlighted_title")
        
        # Exclude invalid reviews
        if not url or str(url).strip().upper() == "NA":
            continue
        if not raw_title or not str(raw_title).strip():
            continue
            
        # Determine which title to display
        if highlighted_title and str(highlighted_title).strip():
            display_title = str(highlighted_title).strip()
        else:
            display_title = str(raw_title).strip()
            
        rating = parse_rating(pub.get("star_rating"))
        
        # Normalize Publisher Name (Space + Period + Space)
        pub_name = str(pub.get("publisher_name", "")).strip()
        pub_name = re.sub(r'\s*\.\s*', ' . ', pub_name)
        
        if rating is not None:
            rated_count += 1
            total_rating_sum += rating
            if rating >= 4:
                cat = "GOOD"
            elif rating >= 3:
                cat = "NEUTRAL"
            else:
                cat = "BAD"
        else:
            # Use raw_title for classification to prevent *asterisks* from breaking the match
            cat = classify_unrated(str(raw_title))
            
        valid_reviews.append({
            'title': display_title,
            'publisher': pub_name,
            'rating': rating,
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
                lines.append(f"`{r['publisher']}`")
                
                # 1 blank line between reviews
                if idx < len(unrated) - 1:
                    lines.append("")
            
            # 2 blank lines after subgroup finishes
            lines.extend(["", ""])

    return "\n".join(lines).strip(), movie_slug

def main():
    if len(sys.argv) < 2:
        sys.stderr.write("[ERROR] Missing JSON input path argument.\n")
        sys.stderr.write("Usage: python wsap_output_creator.py <path_to_json>\n")
        sys.exit(1)
        
    input_path = sys.argv[1]
    sys.stderr.write(f"\n[DEBUG] Starting processing for input file: {input_path}\n")
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    except Exception as e:
        sys.stderr.write(f"[ERROR] Failed to read or parse input JSON: {str(e)}\n")
        sys.exit(1)
        
    wsap_msg, slug = generate_whatsapp_message(json_data)
    
    # --- File Saving Logic ---
    try:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(BASE_DIR, "data", "output", "wsap")
        os.makedirs(out_dir, exist_ok=True)
        
        out_path = os.path.join(out_dir, f"wsap_{slug}.txt")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(wsap_msg)
            
        sys.stderr.write(f"[SUCCESS] File successfully written to: {out_path}\n")
    except Exception as e:
        sys.stderr.write(f"[FATAL ERROR] Failed to save output file!\n")
        sys.stderr.write(f"[EXCEPTION DETAILS]: {str(e)}\n")
        traceback.print_exc(file=sys.stderr)

    # Output strict final WhatsApp message to standard out
    print(wsap_msg)

if __name__ == "__main__":
    main()
