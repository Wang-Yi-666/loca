import pytest

from pricing import total_with_tax


def test_basic():
    assert total_with_tax([10.0, 5.0], 0.2) == pytest.approx(18.0)


def test_empty_is_zero():
    assert total_with_tax([], 0.5) == pytest.approx(0.0)


def test_no_tax():
    assert total_with_tax([1.0, 2.0], 0.0) == pytest.approx(3.0)


def test_returns_a_number_not_none():
    assert isinstance(total_with_tax([1.0], 0.0), float)
