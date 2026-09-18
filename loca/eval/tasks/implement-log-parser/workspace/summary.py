"""Log summarising."""

from collections import Counter

from logparse import parse_line


def count_levels(text):
    """Count log levels across a multi-line blob, skipping blank lines."""
    counter = Counter()
    for line in text.splitlines():
        if not line.strip():
            continue
        counter[parse_line(line)["level"]] += 1
    return dict(counter)
