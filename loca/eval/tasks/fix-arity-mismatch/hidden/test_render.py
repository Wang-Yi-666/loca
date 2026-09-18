from main import render
from report import format_row


def test_renders_two_lines():
    assert len(render().splitlines()) == 2


def test_every_line_is_eighteen_wide():
    for line in render().splitlines():
        assert len(line) == 18


def test_labels_and_values_are_present():
    lines = render().splitlines()
    assert lines[0].startswith("reads")
    assert lines[0].endswith("12")
    assert lines[1].startswith("writes")
    assert lines[1].endswith("3")


def test_format_row_contract():
    assert format_row("a", 1) == "a" + " " * 8 + " " * 8 + "1"
    assert len(format_row("a", 1)) == 18
