"""Display-name helpers."""


def normalize(name):
    """Trim, collapse inner whitespace, and title-case a name."""
    return " ".join(name.split()).title()
