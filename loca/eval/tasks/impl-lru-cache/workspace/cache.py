"""A fixed-capacity cache with least-recently-used eviction."""


class LRUCache:
    """Capacity-bounded cache.

    - get(key) returns the stored value, or None when the key is absent.
    - get(key) counts as a use, as does put() on a key that already exists.
    - put(key, value) on a full cache evicts the least recently used entry.
    - put() on an existing key replaces the value without changing the size.
    """

    def __init__(self, capacity):
        raise NotImplementedError

    def get(self, key):
        raise NotImplementedError

    def put(self, key, value):
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError
