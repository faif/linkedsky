import unicodedata


POST_LIMITS = {
    "linkedin": {"text": 3000, "url": 8192},
    "bluesky": {"text": 300, "text_bytes": 3000, "tag": 64, "tag_bytes": 640, "url": 8192},
}


class PostLengthError(ValueError):
    pass


class PostValidationUnavailable(RuntimeError):
    pass


def linkedin_text(description, hashtags):
    return f"{description} {hashtags}" if hashtags else description


def hashtag_value(hashtag):
    return hashtag.replace("#", "")


def grapheme_count(text):
    if hasattr(unicodedata, "iter_graphemes"):
        return sum(1 for _ in unicodedata.iter_graphemes(text))

    try:
        import regex
    except ImportError as error:
        raise PostValidationUnavailable(
            "Bluesky validation is unavailable. Install the project dependencies with "
            "python -m pip install -r requirements.txt, then restart LinkedSky."
        ) from error

    return sum(1 for _ in regex.finditer(r"\X", text))


def check_length(label, count, limit, unit):
    if count > limit:
        raise PostLengthError(f"{label} exceeds {limit:,} {unit} ({count:,} entered).")


def validate_post_lengths(platform, description, hashtags, url):
    limits = POST_LIMITS[platform]
    if platform == "linkedin":
        text = linkedin_text(description, hashtags)
        check_length("LinkedIn post text, including hashtags,", len(text), limits["text"], "characters")
        check_length("LinkedIn article URL", len(url), limits["url"], "characters")
        return

    tags = hashtags.split()
    text = " ".join([description, *tags])
    check_length("Bluesky post text, including hashtags,", len(text.encode("utf-8")), limits["text_bytes"], "UTF-8 bytes")
    check_length("Bluesky post text, including hashtags,", grapheme_count(text), limits["text"], "characters")
    for index, tag in enumerate(tags, start=1):
        value = hashtag_value(tag)
        check_length(f"Bluesky hashtag {index}", len(value.encode("utf-8")), limits["tag_bytes"], "UTF-8 bytes")
        check_length(f"Bluesky hashtag {index}", grapheme_count(value), limits["tag"], "characters")
    check_length("Bluesky article URL", len(url.encode("utf-8")), limits["url"], "UTF-8 bytes")
