"""Interval merging."""


def merge(intervals):
    """Merge overlapping or touching closed intervals."""
    if not intervals:
        return []
    ordered = sorted((list(pair) for pair in intervals), key=lambda pair: (pair[0], pair[1]))
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return merged
