"""Text helpers."""


def slugify(text):
    """Turn a title into a URL slug.

    - Lower-case everything.
    - Keep ASCII letters and digits (a-z, 0-9).
    - Replace every other character with a hyphen.
    - Collapse runs of hyphens into one.
    - Strip leading and trailing hyphens.
    """
    pieces = []
    for char in text.lower():
        if char.isascii() and char.isalnum():
            pieces.append(char)
        else:
            pieces.append("-")
    slug = "".join(pieces)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")
