"""Reporting helpers."""

from utils import parse_duration


def total(texts):
    """Total seconds across a list of duration strings."""
    return sum(parse_duration(t) for t in texts)
