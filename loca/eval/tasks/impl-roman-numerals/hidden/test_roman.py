import pytest

from roman import from_roman, to_roman

CASES = [
    (1, "I"),
    (2, "II"),
    (3, "III"),
    (4, "IV"),
    (5, "V"),
    (9, "IX"),
    (14, "XIV"),
    (40, "XL"),
    (44, "XLIV"),
    (49, "XLIX"),
    (90, "XC"),
    (400, "CD"),
    (900, "CM"),
    (1990, "MCMXC"),
    (2024, "MMXXIV"),
    (3888, "MMMDCCCLXXXVIII"),
    (3999, "MMMCMXCIX"),
]


def test_to_roman():
    for value, expected in CASES:
        assert to_roman(value) == expected, value


def test_from_roman():
    for value, text in CASES:
        assert from_roman(text) == value, text


def test_round_trip_over_the_whole_range():
    for value in range(1, 4000):
        assert from_roman(to_roman(value)) == value


@pytest.mark.parametrize("bad", [0, -1, 4000])
def test_to_roman_range(bad):
    with pytest.raises(ValueError):
        to_roman(bad)


@pytest.mark.parametrize("bad", ["", "ABC", "IIII", "VV", "IC", "XM", "MCMC"])
def test_non_canonical_input_is_rejected(bad):
    with pytest.raises(ValueError):
        from_roman(bad)


def test_lowercase_input_is_rejected():
    with pytest.raises(ValueError):
        from_roman("xiv")
