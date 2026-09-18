"""Renders a small statistics table."""

from report import format_row

ROWS = [("reads", 12), ("writes", 3)]
WIDTH = 9


def render():
    lines = [format_row(label, value, WIDTH) for label, value in ROWS]
    return chr(10).join(lines)
