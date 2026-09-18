"""Greedy word wrapping."""


def wrap(text, width):
    """Wrap `text` into lines of at most `width` characters.

    - Greedy: pack as many whole words as fit, then start a new line.
    - A word longer than `width` goes on its own line, unbroken.
    - An existing newline ends the current line.
    - No line has trailing whitespace.
    - Raise ValueError when width is less than 1.
    """
    raise NotImplementedError
