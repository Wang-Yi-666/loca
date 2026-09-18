import pytest

from config import load
from validators import require_int, require_positive


def test_defaults():
    assert load({}) == {"retries": 2, "timeout": 30}


def test_overrides():
    assert load({"retries": 5, "timeout": 1.5}) == {"retries": 5, "timeout": 1.5}


def test_zero_retries_is_allowed():
    assert load({"retries": 0})["retries"] == 0


def test_negative_retries_rejected():
    with pytest.raises(ValueError, match="retries"):
        load({"retries": -1})


def test_non_integer_retries_rejected():
    with pytest.raises(ValueError, match="retries"):
        load({"retries": 1.5})


def test_bool_is_not_an_int():
    with pytest.raises(ValueError, match="retries"):
        load({"retries": True})


def test_zero_timeout_rejected():
    with pytest.raises(ValueError, match="timeout"):
        load({"timeout": 0})


def test_negative_timeout_rejected():
    with pytest.raises(ValueError, match="timeout"):
        load({"timeout": -5})


def test_non_numeric_timeout_rejected():
    with pytest.raises(ValueError, match="timeout"):
        load({"timeout": "30"})


def test_validators_return_the_value():
    assert require_int("n", 3, minimum=1) == 3
    assert require_positive("t", 0.5) == 0.5
