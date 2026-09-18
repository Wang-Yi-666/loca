"""Small integer maths helpers."""


def factorial(n):
    """n! for n >= 0."""
    if n == 1:
        return 1
    return n * factorial(n - 1)
