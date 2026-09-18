"""A tiny name -> callable registry."""

_REGISTRY = {}


def register(name, func):
    """Register `func` under `name`, replacing any previous entry."""
    _REGISTRY[name] = func


def get(name):
    """Return the callable registered under `name`.

    Raise KeyError when the name is unknown.
    """
    return _REGISTRY[name]


def names():
    """Registered names, sorted alphabetically."""
    return sorted(_REGISTRY)
