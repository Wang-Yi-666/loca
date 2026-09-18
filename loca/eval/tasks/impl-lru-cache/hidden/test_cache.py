import pytest

from cache import LRUCache


def test_put_and_get():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None


def test_evicts_the_least_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_put_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 10


def test_overwrite_does_not_grow_the_cache():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("a", 2)
    cache.put("b", 3)
    cache.put("c", 4)
    assert cache.get("a") is None
    assert cache.get("c") == 4
    assert cache.get("b") == 3


def test_capacity_of_one():
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") is None
    assert cache.get("b") == 2


def test_len_tracks_entries():
    cache = LRUCache(3)
    assert len(cache) == 0
    cache.put("a", 1)
    cache.put("b", 2)
    assert len(cache) == 2
    cache.put("a", 9)
    assert len(cache) == 2


def test_zero_capacity_stores_nothing():
    cache = LRUCache(0)
    cache.put("a", 1)
    assert cache.get("a") is None
    assert len(cache) == 0


def test_values_may_be_falsy():
    cache = LRUCache(2)
    cache.put("zero", 0)
    cache.put("none", None)
    assert cache.get("zero") == 0
    assert cache.get("none") is None
    assert len(cache) == 2
