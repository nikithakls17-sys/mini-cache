"""
cache.py - the "brain" of the mini cache server.

It stores key -> value pairs in memory, like a Python dictionary,
but with two extra rules:

  1. LRU eviction: the cache has a maximum size (capacity). When it is full
     and a new key comes in, it throws out the Least Recently Used key
     (the one nobody has touched for the longest time).

  2. Expiry (TTL = "time to live"): a key can be given a number of seconds.
     After that time it counts as gone.

How LRU stays fast (O(1) for get, set and delete):
  - A hash map (Python dict) finds any key instantly:  key -> node
  - A doubly linked list keeps the ORDER of use:
        head (newest) <-> ... <-> ... <-> tail (oldest)
    Moving a node to the front, or removing the tail, only changes a few
    pointers, so it is also instant.
"""

import math
import threading
import time


class Node:
    """One box in the doubly linked list. Holds one key/value pair."""

    def __init__(self, key, value, expires_at=None):
        self.key = key                # the key, e.g. "name"
        self.value = value            # the value, e.g. "Niki"
        self.expires_at = expires_at  # a time in seconds, or None = never expires
        self.prev = None              # the box before me (newer)
        self.next = None              # the box after me (older)


class LRUCache:
    def __init__(self, capacity=100, clock=time.monotonic):
        if capacity <= 0:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity      # max number of keys we keep
        self.map = {}                 # the hash map: key -> Node
        self.clock = clock            # where we read "now" from (tests can fake it)
        self.lock = threading.Lock()  # stops two clients changing the cache at the same time

        # Two "dummy" boxes that are always there. They make the list code
        # simpler: we never have to check "is the list empty?".
        self.head = Node(None, None)  # in front of the newest real box
        self.tail = Node(None, None)  # behind the oldest real box
        self.head.next = self.tail
        self.tail.prev = self.head

    # ---------- small linked-list helpers (all O(1)) ----------

    def _remove(self, node):
        """Unhook a box from the list by joining its neighbours to each other."""
        node.prev.next = node.next
        node.next.prev = node.prev

    def _add_to_front(self, node):
        """Put a box right after head, so it becomes the newest."""
        node.prev = self.head
        node.next = self.head.next
        self.head.next.prev = node
        self.head.next = node

    def _is_expired(self, node):
        return node.expires_at is not None and self.clock() >= node.expires_at

    def _delete_node(self, node):
        """Remove a box from both the list and the hash map."""
        self._remove(node)
        del self.map[node.key]

    # ---------- the public operations ----------

    def set(self, key, value, ttl=None):
        """Store a value. ttl = seconds until it expires (None = never)."""
        # isfinite rules out "nan" and "inf", which would make a key that never expires
        if ttl is not None and not (math.isfinite(ttl) and ttl > 0):
            raise ValueError("ttl must be a positive number of seconds")
        expires_at = self.clock() + ttl if ttl is not None else None

        with self.lock:
            if key in self.map:                # key already there: update it
                node = self.map[key]
                node.value = value
                node.expires_at = expires_at
                self._remove(node)             # and mark it as just used
                self._add_to_front(node)
                return

            if len(self.map) >= self.capacity:  # full: throw out the oldest
                oldest = self.tail.prev
                self._delete_node(oldest)

            node = Node(key, value, expires_at)  # brand-new key
            self.map[key] = node
            self._add_to_front(node)

    def get(self, key):
        """Return the value, or None if the key is missing or expired."""
        with self.lock:
            node = self.map.get(key)
            if node is None:
                return None
            if self._is_expired(node):        # expired: clean it up, act like it's missing
                self._delete_node(node)
                return None
            self._remove(node)                # reading it counts as "using" it,
            self._add_to_front(node)          # so it moves to the front
            return node.value

    def delete(self, key):
        """Remove a key. Returns True if it was there."""
        with self.lock:
            node = self.map.get(key)
            if node is None:
                return False
            self._delete_node(node)
            return True

    def size(self):
        """How many keys are stored (expired ones are cleaned up first)."""
        with self.lock:
            for node in list(self.map.values()):
                if self._is_expired(node):
                    self._delete_node(node)
            return len(self.map)

    def keys_newest_first(self):
        """List keys from most to least recently used (handy for testing)."""
        with self.lock:
            keys = []
            node = self.head.next
            while node is not self.tail:
                keys.append(node.key)
                node = node.next
            return keys
