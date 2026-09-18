"""Basic descriptive statistics."""


def average(numbers):
    """Arithmetic mean. Raise ValueError for an empty input."""
    if not numbers:
        raise ValueError("cannot average an empty sequence")
    total = 0
    for number in numbers:
        total += number
    return total / len(numbers)
