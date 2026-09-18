import pytest

from shapes import describe_circle


def test_describes_both_measurements():
    assert describe_circle(1) == "radius 1: area 3.14, perimeter 6.28"


def test_two_decimal_places():
    assert describe_circle(2) == "radius 2: area 12.57, perimeter 12.57"


def test_negative_radius_propagates_value_error():
    with pytest.raises(ValueError):
        describe_circle(-1)
