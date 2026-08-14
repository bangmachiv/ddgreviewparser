import json
import sys
import os

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
            
        lines = [f"{emoji} *{title}*", f"`{pub_name}`"]
        
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
        print("Usage: python generate_wsap.py <path_to_json>")
        sys.exit(1)
        
    input_path = sys.argv[1]
    
    with open(input_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
        
    wsap_msg, slug = generate_whatsapp_message(json_data)
    
    # Create the output folder and save the file securely 
    try:
        out_dir = os.path.join("data", "output", "wsap")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"wsap_{slug}.txt")
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(wsap_msg)
    except Exception:
        # Ignore write errors to guarantee the single print standard out target is not polluted
        pass

    # 12. Print only the final WhatsApp message
    print(wsap_msg)

if __name__ == "__main__":
    main()
