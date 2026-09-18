"""Duration parsing."""

import re

_UNITS = {"h": 3600, "m": 60, "s": 1}
_PATTERN = re.compile(r"([0-9]+)([hms])")


def parse_duration(text):
    """Parse '1h30m' into seconds. Raise ValueError on anything unparsable."""
    if not text:
        raise ValueError("empty duration")
    matches = _PATTERN.findall(text)
    if not matches or "".join(n + u for n, u in matches) != text:
        raise ValueError(f"cannot parse {text!r}")
    return sum(int(n) * _UNITS[u] for n, u in matches)
