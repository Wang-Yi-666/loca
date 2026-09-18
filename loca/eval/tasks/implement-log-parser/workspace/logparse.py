"""Parsing for the application log format."""


def parse_line(line):
    """Parse one log line: '2024-05-01T10:00:00 LEVEL message'.

    The first field must be a timestamp of the form YYYY-MM-DDTHH:MM:SS
    (digits and separators only) and the second must be letters only.

    Return a dict with keys:
      - timestamp: the first field, unchanged
      - level: the second field, upper-cased
      - message: everything after the second field, with inner spacing kept,
        or "" when the line ends after the level

    Raise ValueError when either field is missing or malformed.
    """
    raise NotImplementedError
