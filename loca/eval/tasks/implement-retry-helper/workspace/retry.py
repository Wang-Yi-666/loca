"""A tiny retry helper."""


def call_with_retry(func, times, delay=0.0, sleep=None):
    """Call `func()` until it stops raising, up to `times` attempts.

    - Return the first successful result.
    - Re-raise the last exception when every attempt fails.
    - Call sleep(delay) between attempts, but never after the last one.
    - Raise ValueError when `times` is less than 1.
    - `sleep` defaults to time.sleep, but must be injectable for tests.
    """
    raise NotImplementedError
