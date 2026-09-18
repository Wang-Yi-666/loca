"""A tiny retry helper."""

import time


def call_with_retry(func, times, delay=0.0, sleep=None):
    """Call `func()` until it stops raising, up to `times` attempts."""
    if times < 1:
        raise ValueError("times must be at least 1")
    sleeper = sleep if sleep is not None else time.sleep
    last: Exception | None = None
    for attempt in range(times):
        try:
            return func()
        except Exception as exc:
            last = exc
            if attempt < times - 1:
                sleeper(delay)
    raise last
