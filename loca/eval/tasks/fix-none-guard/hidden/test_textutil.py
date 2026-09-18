from textutil import initials


def test_two_names():
    assert initials("Ada Lovelace") == "AL"


def test_blank_returns_empty():
    assert initials("") == ""


def test_none_returns_empty():
    assert initials(None) == ""


def test_extra_whitespace():
    assert initials("  grace   hopper ") == "GH"


def test_single_name():
    assert initials("ada") == "A"
