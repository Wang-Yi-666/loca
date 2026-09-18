"""Text helpers."""


def slugify(text):
    """Turn a title into a URL slug.

    - Lower-case everything.
    - Keep ASCII letters and digits (a-z, 0-9).
    - Replace every other character with a hyphen.
    - Collapse runs of hyphens into one.
    - Strip leading and trailing hyphens.

    "Hello,  World!" -> "hello-world"
    "  A_B  "        -> "a-b"
    "Study in C++"   -> "study-in-c"
    "Aero 2024"      -> "aero-2024"
    """
    raise NotImplementedError
