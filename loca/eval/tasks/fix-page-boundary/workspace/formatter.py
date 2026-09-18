"""Paginated rendering."""

from pager import page_bounds

ITEMS = list(range(1, 26))


def page(page_number, size=10):
    """Items on 1-based `page_number`."""
    start, end = page_bounds(len(ITEMS), page_number, size)
    return ITEMS[start:end]
