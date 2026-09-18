import pytest

from wrap import wrap

NEWLINE = chr(10)


def test_simple_wrap():
    assert wrap("the quick brown fox", 10) == ["the quick", "brown fox"]


def test_exact_fit():
    assert wrap("aaa bbb", 7) == ["aaa bbb"]


def test_one_word_per_line_when_narrow():
    assert wrap("aa bb cc", 2) == ["aa", "bb", "cc"]


def test_long_word_is_not_split():
    assert wrap("a supercalifragilistic b", 5) == ["a", "supercalifragilistic", "b"]


def test_existing_newline_forces_a_break():
    assert wrap("one two" + NEWLINE + "three four", 20) == ["one two", "three four"]


def test_empty_text():
    assert wrap("", 10) == []


def test_no_trailing_whitespace():
    for line in wrap("a b c d e f g", 3):
        assert line == line.rstrip()


def test_all_words_are_preserved():
    text = "alpha beta gamma delta epsilon"
    joined = " ".join(wrap(text, 11))
    assert joined.split() == text.split()


@pytest.mark.parametrize("bad", [0, -1])
def test_width_must_be_positive(bad):
    with pytest.raises(ValueError):
        wrap("x", bad)


def test_width_of_one():
    assert wrap("a b", 1) == ["a", "b"]
