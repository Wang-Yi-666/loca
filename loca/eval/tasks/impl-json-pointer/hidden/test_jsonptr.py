import pytest

from jsonptr import resolve

DOC = {
    "a": {"b": [10, 20, {"c": "deep"}]},
    "m~n": 1,
    "p/q": 2,
    "": 3,
    " ": 4,
    "~1": 5,
}


def test_empty_pointer_returns_the_document():
    assert resolve(DOC, "") == DOC


def test_escaped_tilde():
    assert resolve(DOC, "/m~0n") == 1


def test_escaped_slash():
    assert resolve(DOC, "/p~1q") == 2


def test_literal_tilde_one_key():
    assert resolve(DOC, "/~01") == 5


def test_list_index():
    assert resolve(DOC, "/a/b/1") == 20


def test_nested_object_in_a_list():
    assert resolve(DOC, "/a/b/2/c") == "deep"


def test_empty_key():
    assert resolve(DOC, "/") == 3


def test_space_key():
    assert resolve(DOC, "/ ") == 4


def test_missing_key_raises_keyerror():
    with pytest.raises(KeyError):
        resolve(DOC, "/nope")


def test_missing_index_raises_indexerror():
    with pytest.raises(IndexError):
        resolve(DOC, "/a/b/9")


def test_non_numeric_index_raises_indexerror():
    with pytest.raises(IndexError):
        resolve(DOC, "/a/b/x")


def test_leading_zero_index_is_rejected():
    with pytest.raises(IndexError):
        resolve(DOC, "/a/b/01")
