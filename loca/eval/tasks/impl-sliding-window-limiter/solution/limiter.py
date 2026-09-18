"""A sliding-window rate limiter."""


class SlidingWindowLimiter:
    """Allow at most `limit` events in any `window`-second span."""

    def __init__(self, limit, window):
        self.limit = limit
        self.window = window
        self._events = []

    def allow(self, now):
        self._events = [t for t in self._events if now - t < self.window]
        if len(self._events) >= self.limit:
            return False
        self._events.append(now)
        return True
