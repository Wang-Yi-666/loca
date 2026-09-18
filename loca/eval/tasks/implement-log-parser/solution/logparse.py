"""Parsing for the application log format."""

import re

_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")
_LEVEL = re.compile(r"[A-Za-z]+")


def parse_line(line):
    """Parse one log line: '2024-05-01T10:00:00 LEVEL message'."""
    parts = line.split(" ", 2)
    if len(parts) < 2:
        raise ValueError(f"not a log line: {line!r}")
    timestamp, level = parts[0], parts[1]
    if not _TIMESTAMP.fullmatch(timestamp) or not _LEVEL.fullmatch(level):
        raise ValueError(f"not a log line: {line!r}")
    message = parts[2] if len(parts) > 2 else ""
    return {"timestamp": timestamp, "level": level.upper(), "message": message}
