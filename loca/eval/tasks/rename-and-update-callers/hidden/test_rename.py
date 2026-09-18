import pytest

import calc
from a import report_a
from b import report_b


def test_new_name_works():
    assert calc.total([1, 2, 3]) == 6


def test_first_caller_was_updated():
    assert report_a([1, 2]) == 3


def test_second_caller_was_updated():
    assert report_b([4, 5]) == 9


def test_old_name_is_gone():
    assert not hasattr(calc, "calc_total")


def test_no_module_still_mentions_the_old_name():
    from pathlib import Path

    here = Path(__file__).resolve().parent
    for name in ("calc.py", "a.py", "b.py"):
        source = (here / name).read_text(encoding="utf-8")
        assert "calc_total" not in source, name
