#!/usr/bin/env python3
"""
classify_reviews.py
"""

import os
import json

REVIEW_PHRASES = [
    "review",
    "movie review",
    "film review",
    "hindi review",
    "hindi movie review",
    "रिव्यू",
    "समीक्षा",
    "मूवी रिव्यू",
    "मूवी समीक्षा",
    "फिल्म रिव्यू",
    "फिल्म समीक्षा",
    "हिंदी रिव्यू"
]

NEGATIVE_PHRASES = [
    "compilation","roundup","video","podcast","twitter","reddit",
    "explained","ending explained","ending","analysis","breakdown",
    "box office","collection","trailer","teaser","cast","songs",
    "soundtrack","ott","streaming","preview","first look","featurette",
    "reaction","reactions","news","live updates"
]

def normalize_title(title:str)->str:
    if not title:
        return ""
    title=title.lower()
    out=[]
    for ch in title:
        out.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return " ".join("".join(out).split())

def normalize_movie_name(name:str)->str:
    return normalize_title(name)

def get_movie_substrings(normalized_name:str):
    words=normalized_name.split()
    return [" ".join(words[:i]) for i in range(1,len(words)+1)]

def generate_valid_combinations(movie_substrings):
    combos=set()
    for sub in movie_substrings:
        for phrase in REVIEW_PHRASES:
            combos.add(f"{sub} {phrase}")
            combos.add(f"{phrase} {sub}")
    return sorted(combos,key=len,reverse=True)

def check_if_review(title,valid_combos):
    norm_title=normalize_title(title)
    padded=f" {norm_title} "
    for neg in NEGATIVE_PHRASES:
        if f" {neg} " in padded:
            return False
    for combo in valid_combos:
        if norm_title==combo or norm_title.startswith(combo+" "):
            return True
    return False

def main():
    base=os.path.dirname(os.path.abspath(__file__))
    movies_file=os.path.join(base,"data","movies","movies-live-today.json")
    searches_dir=os.path.join(base,"data","searches")
    reviews_dir=os.path.join(base,"data","reviews")
    os.makedirs(reviews_dir,exist_ok=True)

    with open(movies_file,encoding="utf-8") as f:
        movies=json.load(f)["movies"]

    for movie in movies:
        slug=movie["slug"]
        search_file=os.path.join(searches_dir,f"search_{slug}.json")
        if not os.path.exists(search_file):
            continue

        with open(search_file,encoding="utf-8") as f:
            search_data=json.load(f)

        combos=generate_valid_combinations(
            get_movie_substrings(normalize_movie_name(movie["name"]))
        )

        reviews_output={
            "movie":{
                "name":movie["name"],
                "slug":slug,
                "date":movie["date"]
            },
            "publishers":[]
        }

        for pub in search_data.get("publishers",[]):
            first=None
            for result in pub.get("results",[]):
                ok=check_if_review(result.get("title",""),combos)
                result["is_review"]="Y" if ok else "N"
                if ok and first is None:
                    first=result

            reviews_output["publishers"].append({
                "publisher_id":pub.get("publisher_id",""),
                "publisher_name":pub.get("publisher_name",""),
                "review_url": first.get("url","NA") if first else "NA",
                "review_title": first.get("title","NA") if first else "NA",
                "search_rank": first.get("rank","NA") if first else "NA"
            })

        with open(search_file,"w",encoding="utf-8") as f:
            json.dump(search_data,f,ensure_ascii=False,indent=2)

        with open(os.path.join(reviews_dir,f"reviews_{slug}.json"),"w",encoding="utf-8") as f:
            json.dump(reviews_output,f,ensure_ascii=False,indent=2)

        print(f"Processed {slug}")

if __name__=="__main__":
    main()
