"""Slice bounds for paginated output."""


def page_bounds(total, page, size):
    """Return (start, end) slice bounds for 1-based `page`.

    Python slicing tolerates bounds past the end of a sequence, so a page
    beyond the last one simply yields an empty slice.
    """
    start = page * size
    return start, start + size
