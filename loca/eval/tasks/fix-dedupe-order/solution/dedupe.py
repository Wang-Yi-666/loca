"""De-duplication helpers."""


def unique(items):
    """De-duplicate, keeping the order of first appearance."""
    return list(dict.fromkeys(items))
