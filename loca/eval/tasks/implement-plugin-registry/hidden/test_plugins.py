import pytest

from app import apply, build
from plugins import get, names, register


def test_build_returns_sorted_names():
    assert build() == ["shout", "whisper"]


def test_apply_dispatches():
    build()
    assert apply("shout", "hi") == "HI"
    assert apply("whisper", "HI") == "hi"


def test_unknown_name_raises_keyerror():
    build()
    with pytest.raises(KeyError):
        apply("nope", "hi")


def test_registering_twice_overwrites():
    register("twice", lambda text: text)
    register("twice", lambda text: text + "!")
    assert get("twice")("x") == "x!"


def test_names_reflects_latest_registrations():
    register("zzz", lambda text: text)
    assert names() == sorted(names())
    assert "zzz" in names()
