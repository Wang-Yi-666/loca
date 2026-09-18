"""Roman numeral conversion."""

MIN_VALUE = 1
MAX_VALUE = 3999

_TABLE = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]

_DIGITS = set("MDCLXVI")


def to_roman(value):
    """Convert an integer in 1..3999 to a Roman numeral."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("value must be an integer")
    if value < MIN_VALUE or value > MAX_VALUE:
        raise ValueError(f"value must be in {MIN_VALUE}..{MAX_VALUE}")
    pieces = []
    remaining = value
    for amount, numeral in _TABLE:
        while remaining >= amount:
            pieces.append(numeral)
            remaining -= amount
    return "".join(pieces)


def from_roman(text):
    """Parse a canonical upper-case Roman numeral."""
    if not isinstance(text, str) or not text:
        raise ValueError("empty numeral")
    if text != text.upper() or any(char not in _DIGITS for char in text):
        raise ValueError(f"invalid numeral {text!r}")
    value = 0
    index = 0
    for amount, numeral in _TABLE:
        while text.startswith(numeral, index):
            value += amount
            index += len(numeral)
    if index != len(text) or to_roman(value) != text:
        raise ValueError(f"non-canonical numeral {text!r}")
    return value
