"""Circle geometry."""

import math


def circle_area(radius):
    if radius < 0:
        raise ValueError("radius must not be negative")
    return math.pi * radius**2


def circle_perimeter(radius):
    if radius < 0:
        raise ValueError("radius must not be negative")
    return 2 * math.pi * radius
