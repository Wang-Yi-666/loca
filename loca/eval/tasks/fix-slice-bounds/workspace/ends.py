"""Helpers for inspecting the ends of a sequence."""


def first_and_last(items):
    """Return (first, last) of a non-empty sequence."""
    return items[0], items[len(items)]
