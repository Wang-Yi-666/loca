from parity import is_even


def test_even_is_true():
    assert is_even(4) is True


def test_odd_is_false():
    assert is_even(5) is False


def test_zero_is_even():
    assert is_even(0) is True


def test_negative_is_handled():
    assert is_even(-3) is False


def test_not_a_string():
    assert not isinstance(is_even(2), str)
