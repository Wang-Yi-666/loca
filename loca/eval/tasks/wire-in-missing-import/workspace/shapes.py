"""Report helpers for shape measurements."""

LABELS = {"area": "area", "perimeter": "perimeter"}


def describe_circle(radius):
    """Return a one-line description of a circle's area and perimeter."""
    return (
        f"radius {radius}: {LABELS['area']} {circle_area(radius):.2f}, "
        f"{LABELS['perimeter']} {circle_perimeter(radius):.2f}"
    )
