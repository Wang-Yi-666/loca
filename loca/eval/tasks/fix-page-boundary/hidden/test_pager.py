from formatter import ITEMS, page
from pager import page_bounds


def test_first_page():
    assert page(1) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_second_page():
    assert page(2) == [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]


def test_last_partial_page():
    assert page(3) == [21, 22, 23, 24, 25]


def test_beyond_the_end_is_empty():
    assert page(4) == []


def test_custom_size():
    assert page(1, size=5) == [1, 2, 3, 4, 5]
    assert page(5, size=5) == [21, 22, 23, 24, 25]


def test_bounds_are_consistent_with_page():
    for number in range(1, 6):
        start, end = page_bounds(len(ITEMS), number, 10)
        assert ITEMS[start:end] == page(number)
