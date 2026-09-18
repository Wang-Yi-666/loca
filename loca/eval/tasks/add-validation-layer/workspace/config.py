"""Config loading with validation."""

from validators import require_int, require_positive

DEFAULTS = {"retries": 2, "timeout": 30}


def load(raw):
    """Merge `raw` over DEFAULTS, validating the two known keys."""
    merged = {**DEFAULTS, **raw}
    require_int("retries", merged["retries"])
    require_positive("timeout", merged["timeout"])
    return merged
