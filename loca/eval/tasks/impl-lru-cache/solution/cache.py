"""A fixed-capacity cache with least-recently-used eviction."""

from collections import OrderedDict


class LRUCache:
    """Capacity-bounded cache."""

    def __init__(self, capacity):
        self.capacity = capacity
        self._entries = OrderedDict()

    def get(self, key):
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key, value):
        if key in self._entries:
            self._entries.move_to_end(key)
        self._entries[key] = value
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def __len__(self):
        return len(self._entries)
