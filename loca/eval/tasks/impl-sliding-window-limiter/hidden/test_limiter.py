from limiter import SlidingWindowLimiter


def test_allows_up_to_the_limit():
    limiter = SlidingWindowLimiter(limit=3, window=10)
    assert [limiter.allow(0.0) for _ in range(3)] == [True, True, True]
    assert limiter.allow(0.0) is False


def test_old_events_leave_the_window():
    limiter = SlidingWindowLimiter(limit=2, window=10)
    assert limiter.allow(0.0) is True
    assert limiter.allow(1.0) is True
    assert limiter.allow(1.0) is False
    assert limiter.allow(10.0) is True


def test_rejected_calls_do_not_consume_budget():
    limiter = SlidingWindowLimiter(limit=1, window=5)
    assert limiter.allow(0.0) is True
    assert limiter.allow(1.0) is False
    assert limiter.allow(5.0) is True


def test_window_boundary_is_half_open():
    limiter = SlidingWindowLimiter(limit=1, window=10)
    assert limiter.allow(0.0) is True
    assert limiter.allow(9.9) is False
    assert limiter.allow(10.0) is True


def test_spread_out_calls_are_all_allowed():
    limiter = SlidingWindowLimiter(limit=2, window=10)
    assert limiter.allow(0.0) is True
    assert limiter.allow(5.0) is True
    assert limiter.allow(10.0) is True
    assert limiter.allow(15.0) is True


def test_time_may_go_backwards_without_crashing():
    limiter = SlidingWindowLimiter(limit=2, window=10)
    assert limiter.allow(100.0) is True
    assert limiter.allow(0.0) is True
    assert limiter.allow(0.0) is False


def test_limit_of_one():
    limiter = SlidingWindowLimiter(limit=1, window=1)
    assert limiter.allow(0.0) is True
    assert limiter.allow(0.5) is False
    assert limiter.allow(1.0) is True
