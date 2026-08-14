import json
import sys
import os
import traceback

def generate_whatsapp_message(json_data):
    """
    Takes a parsed JSON dictionary, processes it deterministically,
    and returns a WhatsApp-formatted plain-text string.
    """
    movie_name = json_data.get("movie", {}).get("name", "Unknown Movie")
    movie_slug = json_data.get("movie", {}).get("slug", "unknown_slug")
    
    # 1 & 2: Parse JSON and identify valid reviews
    valid_reviews = []
    
    for idx, pub in enumerate(json_data.get("publishers", [])):
        review_url = pub.get("review_url")
        clean_title = pub.get("clean_title")
        
        # Exclude records with missing URLs/NA or missing/empty clean_title
        if not review_url or str(review_url).strip().upper() == "NA":
            continue
        if not clean_title or not str(clean_title).strip():
            continue
            
        valid_reviews.append((idx, pub))
        
    # 4. Parse numeric ratings safely
    def get_rating(val):
        if val in (None, "", "Na", "NA", "null") or "could not find" in str(val).lower():
            return None
        try:
            return float(val)
        except ValueError:
            return None

    # 8. Categorise unrated reviews based on clean-title sentiment
    def classify_unrated(title):
        title_lower = title.lower()
        bad_phrases = ["pointless", "painful", "fails to impress", "can't save this film", 
                       "delivers little", "unfunny", "absurd", "nightmare", 
                       "strains patience", "bad", "poor", "disappointing"]
        good_phrases = ["excellent", "brilliant", "outstanding", "terrific", 
                        "superb", "delightful", "impressive", "entertaining"]
        
        for bp in bad_phrases:
            if bp in title_lower:
                return "BAD"
        for gp in good_phrases:
            if gp in title_lower:
                return "GOOD"
        return "NEUTRAL"
        
    rated_count = 0
    total_rating = 0.0
    
    categories = {
        "GOOD": [],
        "NEUTRAL": [],
        "BAD": []
    }
    
    # 7 & 8: Categorise all valid reviews
    for idx, rev in valid_reviews:
        rating = get_rating(rev.get("star_rating"))
        
        if rating is not None:
            # 6. Count only valid numeric ratings for the average
            rated_count += 1
            total_rating += rating
            if rating > 3.5:
                cat = "GOOD"
            elif rating >= 2.5:
                cat = "NEUTRAL"
            else:
                cat = "BAD"
                
            categories[cat].append({
                "is_unrated": False,
                "rating": rating,
                "idx": idx,
                "data": rev
            })
        else:
            cat = classify_unrated(str(rev.get("clean_title", "")))
            categories[cat].append({
                "is_unrated": True,
                "rating": -1.0, # Dummy sorting value
                "idx": idx,
                "data": rev
            })
            
    # 5. Calculate Average 
    avg_rating = 0.0
    if rated_count > 0:
        avg_rating = round(total_rating / rated_count, 1)
        
    # Helper to generate exact WhatsApp star emoji representation
    def format_stars(rating):
        if rating == 0.5:
            return "💫"
        full = int(rating)
        half = rating - full
        stars = "⭐" * full
        if half >= 0.5:
            stars += "💫"
        return stars
        
    def format_review_block(item, cat):
        rev = item["data"]
        # 3. Extract exact clean_title
        title = str(rev.get("clean_title", "")).strip()
        pub_name = str(rev.get("publisher_name", "")).strip()
        critic = str(rev.get("critic_name", "")).strip()
        
        if item["is_unrated"]:
            emoji = {"GOOD": "🙂", "NEUTRAL": "😐", "BAD": "☹️"}[cat]
        else:
            emoji = format_stars(item["rating"])
            
        # Updated to place stars and title on separate lines
        lines = [
            emoji, 
            f"*{title}*", 
            f"`{pub_name}`"
        ]
        
        # Determine if critic should be omitted
        if critic and critic.lower() not in ("na", "null", "none", ""):
            lines.append(f"_{critic}_")
            
        return "\n".join(lines)
        
    # 10. Sort each category correctly
    for cat in ["GOOD", "NEUTRAL", "BAD"]:
        # Sort by: Rated first (False < True), then Highest Rating, then Original JSON order
        categories[cat].sort(key=lambda x: (x["is_unrated"], -x["rating"], x["idx"]))
        
    # 11. Generate final WhatsApp formatting
    out = []
    out.append(f"*{movie_name}*")
    out.append("")
    out.append(f"Average Rating : *{avg_rating:.1f}/5* `{rated_count} Reviews`")
    
    emoji_map = {"GOOD": "🟢", "NEUTRAL": "🟡", "BAD": "🔴"}
    
    # Strictly respect the 1. GOOD, 2. NEUTRAL, 3. BAD category order
    for cat in ["GOOD", "NEUTRAL", "BAD"]:
        items = categories[cat]
        
        # 9. Count ALL reviews in each category
        out.append("")
        out.append(f"*{emoji_map[cat]} {cat} ({len(items)})*")
        
        for item in items:
            out.append("")
            out.append(format_review_block(item, cat))
            
    return "\n".join(out), movie_slug

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
    
    try:
        # Build absolute path to guarantee correct directory targeting
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        sys.stderr.write(f"[DEBUG] Script Base Directory resolved to: {BASE_DIR}\n")
        
        out_dir = os.path.join(BASE_DIR, "data", "output", "wsap")
        sys.stderr.write(f"[DEBUG] Target Output Directory: {out_dir}\n")
        
        # Force creation of directory structure
        os.makedirs(out_dir, exist_ok=True)
        sys.stderr.write(f"[DEBUG] Target directory verified/created successfully.\n")
        
        # Write to file
        out_path = os.path.join(out_dir, f"wsap_{slug}.txt")
        sys.stderr.write(f"[DEBUG] Attempting to write file: {out_path}\n")
        
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(wsap_msg)
            
        sys.stderr.write(f"[SUCCESS] File successfully written to: {out_path}\n")
        
    except Exception as e:
        sys.stderr.write(f"[FATAL ERROR] Failed to save output file!\n")
        sys.stderr.write(f"[EXCEPTION DETAILS]: {str(e)}\n")
        traceback.print_exc(file=sys.stderr)

    # Print only the final WhatsApp message to standard output
    print(wsap_msg)

if __name__ == "__main__":
    main()
