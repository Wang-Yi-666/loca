"""Value validators used by the config loader."""


def require_int(name, value, minimum=0):
    """Return `value` when it is an int >= `minimum`.

    Otherwise raise ValueError whose message mentions `name`. A bool is NOT
    accepted, even though bool subclasses int.
    """
    raise NotImplementedError


def require_positive(name, value):
    """Return `value` when it is a number greater than zero.

    Otherwise raise ValueError whose message mentions `name`. A bool is NOT
    accepted.
    """
    raise NotImplementedError
