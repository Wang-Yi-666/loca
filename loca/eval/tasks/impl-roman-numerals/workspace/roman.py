"""Roman numeral conversion."""

MIN_VALUE = 1
MAX_VALUE = 3999


def to_roman(value):
    """Convert an integer in 1..3999 to a Roman numeral.

    Raise ValueError outside that range.
    """
    raise NotImplementedError


def from_roman(text):
    """Parse an upper-case Roman numeral for a value in 1..3999.

    The input must be in canonical upper-case form: from_roman(to_roman(n))
    == n for every n in range, and anything to_roman would never emit (such as
    "IIII" or "VV") raises ValueError. Lower-case input is rejected too.
    """
    raise NotImplementedError
