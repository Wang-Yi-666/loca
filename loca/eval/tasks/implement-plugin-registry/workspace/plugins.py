"""A tiny name -> callable registry."""

_REGISTRY = {}


def register(name, func):
    """Register `func` under `name`, replacing any previous entry."""
    raise NotImplementedError


def get(name):
    """Return the callable registered under `name`.

    Raise KeyError when the name is unknown.
    """
    raise NotImplementedError


def names():
    """Registered names, sorted alphabetically."""
    raise NotImplementedError
