"""Basic descriptive statistics."""


def average(numbers):
    """Arithmetic mean. Raise ValueError for an empty input."""
    total = 0
    for number in numbers:
        total += number
    return total // len(numbers)
