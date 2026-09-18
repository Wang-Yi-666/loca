"""Word frequency counting."""


def count_words(text):
    """Count whitespace-separated words, case-insensitively."""
    counts = {}
    for word in text.split():
        key = word.lower()
        counts[key] = counts.get(key, 0) + 1
    return counts
