from pathlib import Path

import pytest

from duration import parse_duration
from main import total


def test_parser_lives_in_duration():
    assert parse_duration("30s") == 30
    assert parse_duration("1h30m") == 5400
    assert parse_duration("2m15s") == 135


def test_parsing_behaviour_is_unchanged():
    with pytest.raises(ValueError):
        parse_duration("")
    with pytest.raises(ValueError):
        parse_duration("abc")
    with pytest.raises(ValueError):
        parse_duration("1x")


def test_caller_was_updated():
    assert total(["1m", "30s"]) == 90


def test_duration_is_not_a_re_export():
    source = (Path(__file__).resolve().parent / "duration.py").read_text(encoding="utf-8")
    assert "utils" not in source
