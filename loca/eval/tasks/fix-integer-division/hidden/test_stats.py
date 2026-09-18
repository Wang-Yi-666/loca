import pytest

from stats import average


def test_mean_is_exact():
    assert average([1, 2, 3, 4]) == 2.5


def test_whole_number_mean():
    assert average([2, 4]) == 3


def test_single_value():
    assert average([5]) == 5


def test_floats():
    assert average([0.5, 0.25]) == 0.375


def test_empty_raises_value_error():
    with pytest.raises(ValueError):
        average([])
