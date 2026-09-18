"""Greedy word wrapping."""


def wrap(text, width):
    """Wrap `text` into lines of at most `width` characters."""
    if width < 1:
        raise ValueError("width must be at least 1")
    lines = []
    for paragraph in text.split(chr(10)):
        current = ""
        for word in paragraph.split():
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= width:
                current = current + " " + word
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines
