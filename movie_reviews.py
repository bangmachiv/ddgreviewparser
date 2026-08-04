import re


def normalize(text):
    text = text.lower()

    # remove punctuation except unicode letters/numbers
    text = re.sub(r"[^\w\s]", " ", text)

    # remove extra spaces
    return " ".join(text.split())


def is_valid_review_title(title, movie_name):

    if ":" not in title:
        return False

    prefix = title.split(":")[0]

    prefix = normalize(prefix)

    movie = normalize(movie_name)

    allowed_words = set(
        movie.split()
        + [
            "movie",
            "review",
            "film"
        ]
    )

    words = prefix.split()

    # every word before colon must be allowed
    for word in words:
        if word not in allowed_words:
            return False

    # must contain review keyword
    if "review" not in words:
        return False

    return True
