import pytest

from blog import post_url
from textutil import slugify

CASES = [
    ("Hello,  World!", "hello-world"),
    ("  A_B  ", "a-b"),
    ("Study in C++", "study-in-c"),
    ("Aero 2024", "aero-2024"),
    ("--already--slugged--", "already-slugged"),
    ("???", ""),
]


def test_slugify_cases():
    for raw, expected in CASES:
        assert slugify(raw) == expected, raw


def test_post_url_uses_the_slug():
    assert post_url("Hello, World!") == "https://example.com/posts/hello-world"


def test_post_url_accepts_a_custom_base():
    assert post_url("Hi There", base="https://x.dev/p") == "https://x.dev/p/hi-there"
