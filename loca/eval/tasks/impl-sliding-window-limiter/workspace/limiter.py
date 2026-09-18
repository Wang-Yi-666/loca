"""A sliding-window rate limiter."""


class SlidingWindowLimiter:
    """Allow at most `limit` events in any `window`-second span.

    Time is supplied by the caller as a float, so the limiter is fully
    deterministic and never reads the clock itself.

    - allow(now) returns True and records the event when the budget allows.
    - allow(now) returns False and records nothing when it does not.
    - An event recorded at time t stops counting once now - t >= window.
    """

    def __init__(self, limit, window):
        raise NotImplementedError

    def allow(self, now):
        raise NotImplementedError
