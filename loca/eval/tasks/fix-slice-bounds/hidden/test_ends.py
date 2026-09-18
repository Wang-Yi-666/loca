import pytest

from ends import first_and_last


def test_two_items():
    assert first_and_last([1, 2]) == (1, 2)


def test_many_items():
    assert first_and_last("abcd") == ("a", "d")


def test_single_item():
    assert first_and_last(["only"]) == ("only", "only")


def test_empty_still_raises():
    with pytest.raises(IndexError):
        first_and_last([])
