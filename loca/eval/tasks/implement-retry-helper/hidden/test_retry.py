import pytest

from retry import call_with_retry


class Boom(Exception):
    pass


def test_returns_the_first_success():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise Boom("not yet")
        return "ok"

    assert call_with_retry(flaky, times=5) == "ok"
    assert len(calls) == 3


def test_succeeds_without_retrying_when_the_first_call_works():
    calls = []

    def fine():
        calls.append(1)
        return 42

    assert call_with_retry(fine, times=3) == 42
    assert len(calls) == 1


def test_reraises_the_last_error():
    def always():
        raise Boom("always")

    with pytest.raises(Boom):
        call_with_retry(always, times=3)


def test_gives_up_after_exactly_times_attempts():
    calls = []

    def always():
        calls.append(1)
        raise Boom("always")

    with pytest.raises(Boom):
        call_with_retry(always, times=4)
    assert len(calls) == 4


def test_sleeps_only_between_attempts():
    slept = []

    def always():
        raise Boom("x")

    with pytest.raises(Boom):
        call_with_retry(always, times=3, delay=0.5, sleep=slept.append)

    assert slept == [0.5, 0.5]


def test_rejects_zero_times():
    with pytest.raises(ValueError):
        call_with_retry(lambda: 1, times=0)


def test_rejects_negative_times():
    with pytest.raises(ValueError):
        call_with_retry(lambda: 1, times=-2)


def test_default_sleep_is_not_used_when_no_delay():
    slept = []

    def fine():
        return 1

    assert call_with_retry(fine, times=2, sleep=slept.append) == 1
    assert slept == []
