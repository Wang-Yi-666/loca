import pytest

from maths import factorial


def test_zero():
    assert factorial(0) == 1


def test_one():
    assert factorial(1) == 1


def test_three():
    assert factorial(3) == 6


def test_six():
    assert factorial(6) == 720


def test_negative_is_rejected():
    with pytest.raises(ValueError):
        factorial(-1)
