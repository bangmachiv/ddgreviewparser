# Updated classify_reviews.py
# NOTE:
# Replace the following functions in your existing script:
# - normalize_movie_name
# - get_movie_substrings
# - check_if_review
#
# Changes:
# * preserves Hindi movie names
# * parses ONLY from beginning
# * longest movie substring first
# * supports both:
#     Movie Review
#     Review Movie
# * checks negative phrases after positive match
# * uses whole-word matching

def normalize_movie_name(name: str) -> str:
    return normalize_title(name)


def get_movie_substrings(normalized_name: str) -> list:
    words = normalized_name.split()
    return [' '.join(words[:i]) for i in range(len(words),0,-1)]


NORMALIZED_NEGATIVES = [normalize_title(x) for x in NEGATIVE_PHRASES]


def check_if_review(title: str, movie_substrings: list) -> bool:
    norm = normalize_title(title)
    tokens = norm.split()

    for sub in movie_substrings:
        sub_tokens = sub.split()

        for phrase in REVIEW_PHRASES:
            p = normalize_title(phrase)
            p_tokens = p.split()

            # movie -> review
            if tokens[:len(sub_tokens)] == sub_tokens and \
               tokens[len(sub_tokens):len(sub_tokens)+len(p_tokens)] == p_tokens:

                padded = " " + norm + " "
                if any((" "+n+" ") in padded for n in NORMALIZED_NEGATIVES):
                    return False
                return True

            # review -> movie
            if tokens[:len(p_tokens)] == p_tokens and \
               tokens[len(p_tokens):len(p_tokens)+len(sub_tokens)] == sub_tokens:

                padded = " " + norm + " "
                if any((" "+n+" ") in padded for n in NORMALIZED_NEGATIVES):
                    return False
                return True

    return False

# In main(), replace:
# valid_combos = generate_valid_combinations(movie_substrings)
#
# with nothing.
#
# And replace:
#
# check_if_review(title, valid_combos)
#
# by
#
# check_if_review(title, movie_substrings)
