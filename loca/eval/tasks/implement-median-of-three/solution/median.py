"""Middle-value helpers."""


def median_of_three(a, b, c):
    """Return the middle value of the three."""
    return sorted((a, b, c))[1]
