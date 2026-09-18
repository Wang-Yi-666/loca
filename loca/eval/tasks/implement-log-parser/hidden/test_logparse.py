import pytest

from logparse import parse_line
from summary import count_levels

LOG = """2024-05-01T10:00:00 INFO started
2024-05-01T10:00:01 WARN slow call
2024-05-01T10:00:02 info done
"""


def test_parses_a_line():
    assert parse_line("2024-05-01T10:00:00 INFO started") == {
        "timestamp": "2024-05-01T10:00:00",
        "level": "INFO",
        "message": "started",
    }


def test_message_keeps_inner_spaces():
    assert parse_line("2024-05-01T10:00:01 WARN slow   call")["message"] == "slow   call"


def test_level_is_upper_cased():
    assert parse_line("2024-05-01T10:00:02 info done")["level"] == "INFO"


def test_message_may_be_empty():
    assert parse_line("2024-05-01T10:00:00 INFO")["message"] == ""


def test_rejects_junk():
    with pytest.raises(ValueError):
        parse_line("not a log line")


def test_summary_counts_levels():
    assert count_levels(LOG) == {"INFO": 2, "WARN": 1}


def test_summary_skips_blank_lines():
    assert count_levels("\n2024-05-01T10:00:00 INFO a\n\n") == {"INFO": 1}
