"""A tiny in-memory table."""

PEOPLE = [
    {"name": "ada", "age": 36},
    {"name": "alan", "age": 41},
    {"name": "grace", "age": 9},
]


def by_age():
    """Names of PEOPLE, oldest first."""
    return [p["name"] for p in sorted(PEOPLE, key=lambda p: str(p["age"]), reverse=True)]
