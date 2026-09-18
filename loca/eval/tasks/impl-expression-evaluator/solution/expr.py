"""A small arithmetic expression evaluator."""


class _Parser:
    def __init__(self, text):
        self.chars = [char for char in text if not char.isspace()]
        self.position = 0

    def peek(self):
        if self.position < len(self.chars):
            return self.chars[self.position]
        return None

    def parse_expression(self):
        value = self.parse_term()
        while self.peek() in ("+", "-"):
            operator = self.chars[self.position]
            self.position += 1
            right = self.parse_term()
            value = value + right if operator == "+" else value - right
        return value

    def parse_term(self):
        value = self.parse_factor()
        while self.peek() in ("*", "/"):
            operator = self.chars[self.position]
            self.position += 1
            right = self.parse_factor()
            value = value * right if operator == "*" else int(value / right)
        return value

    def parse_factor(self):
        char = self.peek()
        if char is None:
            raise ValueError("unexpected end of expression")
        if char == "(":
            self.position += 1
            value = self.parse_expression()
            if self.peek() != ")":
                raise ValueError("unbalanced parentheses")
            self.position += 1
            return value
        if char.isdigit():
            start = self.position
            while self.peek() is not None and self.peek().isdigit():
                self.position += 1
            return int("".join(self.chars[start : self.position]))
        raise ValueError(f"unexpected character {char!r}")


def evaluate(text):
    """Evaluate an arithmetic expression over integers."""
    parser = _Parser(text)
    if not parser.chars:
        raise ValueError("empty expression")
    value = parser.parse_expression()
    if parser.position != len(parser.chars):
        raise ValueError("unexpected trailing input")
    return value
