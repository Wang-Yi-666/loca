import pytest

from expr import evaluate


def test_single_number():
    assert evaluate("42") == 42


def test_precedence():
    assert evaluate("2+3*4") == 14


def test_left_associativity():
    assert evaluate("10-3-2") == 5
    assert evaluate("100/10/2") == 5


def test_parentheses():
    assert evaluate("(2+3)*4") == 20


def test_nested_parentheses():
    assert evaluate("2*(3+(4-1))") == 12


def test_whitespace_is_ignored():
    assert evaluate("  2 + 3 * 4 ") == 14
    assert evaluate("( 1 + 2 ) * 3") == 9


def test_integer_division():
    assert evaluate("7/2") == 3


def test_mixed_expression():
    assert evaluate("1+2*3-4/2") == 5


def test_deeply_nested():
    assert evaluate("((((1+1))))") == 2


@pytest.mark.parametrize("bad", ["", "(1+2", "1+", "*3", "1++2", "()", "abc"])
def test_malformed_input_is_rejected(bad):
    with pytest.raises(ValueError):
        evaluate(bad)
