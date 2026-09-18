"""Blog URL helpers."""

from textutil import slugify


def post_url(title, base="https://example.com/posts"):
    """Full URL for a post with the given title."""
    return f"{base}/{slugify(title)}"
