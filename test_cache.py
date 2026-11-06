"""
test_cache.py - checks that everything works.   Run:  python -m unittest -v
"""

import socket
import struct
import threading
import time
import unittest

from cache import LRUCache
from server import MAX_LINE, handle_command, run_server


class FakeClock:
    """A clock we control, so expiry tests don't have to really wait."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TestLRUCache(unittest.TestCase):
    def test_set_and_get(self):
        cache = LRUCache(capacity=2)
        cache.set("name", "Niki")
        self.assertEqual(cache.get("name"), "Niki")

    def test_missing_key_returns_none(self):
        self.assertIsNone(LRUCache().get("nope"))

    def test_update_existing_key(self):
        cache = LRUCache()
        cache.set("a", "1")
        cache.set("a", "2")
        self.assertEqual(cache.get("a"), "2")
        self.assertEqual(cache.size(), 1)

    def test_evicts_least_recently_used(self):
        cache = LRUCache(capacity=2)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.get("a")          # "a" is now the most recently used
        cache.set("c", "3")     # full, so "b" (least recently used) is thrown out
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), "1")
        self.assertEqual(cache.get("c"), "3")

    def test_order_newest_first(self):
        cache = LRUCache(capacity=3)
        for key in ["a", "b", "c"]:
            cache.set(key, key)
        cache.get("a")
        self.assertEqual(cache.keys_newest_first(), ["a", "c", "b"])

    def test_delete(self):
        cache = LRUCache()
        cache.set("a", "1")
        self.assertTrue(cache.delete("a"))
        self.assertFalse(cache.delete("a"))
        self.assertIsNone(cache.get("a"))

    def test_expiry(self):
        clock = FakeClock()
        cache = LRUCache(clock=clock)
        cache.set("temp", "x", ttl=10)
        clock.now = 9
        self.assertEqual(cache.get("temp"), "x")
        clock.now = 10
        self.assertIsNone(cache.get("temp"))
        self.assertEqual(cache.size(), 0)

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            LRUCache(capacity=0)
        with self.assertRaises(ValueError):
            LRUCache().set("a", "1", ttl=-5)
        for never_expires in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                LRUCache().set("a", "1", ttl=never_expires)

    def test_many_threads_at_once(self):
        cache = LRUCache(capacity=1000)

        def writer(start):
            for i in range(start, start + 100):
                cache.set(f"k{i}", str(i))

        threads = [threading.Thread(target=writer, args=(n * 100,)) for n in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(cache.size(), 1000)


class TestCommands(unittest.TestCase):
    def setUp(self):
        self.cache = LRUCache(capacity=2)

    def test_commands(self):
        self.assertEqual(handle_command(self.cache, "PING"), "PONG")
        self.assertEqual(handle_command(self.cache, "SET name Niki"), "OK")
        self.assertEqual(handle_command(self.cache, "get name"), "VALUE Niki")
        self.assertEqual(handle_command(self.cache, "SIZE"), "SIZE 1")
        self.assertEqual(handle_command(self.cache, "DEL name"), "DELETED")
        self.assertEqual(handle_command(self.cache, "GET name"), "NOT_FOUND")

    def test_errors(self):
        self.assertTrue(handle_command(self.cache, "").startswith("ERROR"))
        self.assertTrue(handle_command(self.cache, "SET onlykey").startswith("ERROR"))
        self.assertTrue(handle_command(self.cache, "SET a b notanumber").startswith("ERROR"))
        self.assertTrue(handle_command(self.cache, "FLY away").startswith("ERROR"))
        self.assertTrue(handle_command(self.cache, "SET a b nan").startswith("ERROR"))
        self.assertEqual(handle_command(self.cache, 'SET a "no end'), "ERROR unclosed quote")

    def test_values_with_spaces(self):
        self.assertEqual(handle_command(self.cache, 'SET msg "hello world"'), "OK")
        self.assertEqual(handle_command(self.cache, "GET msg"), "VALUE hello world")
        self.assertEqual(handle_command(self.cache, "SET quoted 'single quotes' 60"), "OK")
        self.assertEqual(handle_command(self.cache, "GET quoted"), "VALUE single quotes")
        # unquoted extra words are still an error, not a silent mistake
        self.assertTrue(handle_command(self.cache, "SET msg hello world").startswith("ERROR"))

    def test_backslash_and_hash_kept(self):
        self.assertEqual(handle_command(self.cache, r"SET path C:\temp\new"), "OK")
        self.assertEqual(handle_command(self.cache, "GET path"), r"VALUE C:\temp\new")
        self.assertEqual(handle_command(self.cache, "SET tag #1"), "OK")
        self.assertEqual(handle_command(self.cache, "GET tag"), "VALUE #1")


class TestOverNetwork(unittest.TestCase):
    """Starts the real server and talks to it over a TCP socket."""

    PORT = 6399

    @classmethod
    def setUpClass(cls):
        threading.Thread(target=run_server, args=("127.0.0.1", cls.PORT, 10), daemon=True).start()
        for _ in range(50):  # wait until the server is ready
            try:
                socket.create_connection(("127.0.0.1", cls.PORT)).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"test server did not start on port {cls.PORT}")

    def connect(self):
        conn = socket.create_connection(("127.0.0.1", self.PORT), timeout=3)
        return conn, conn.makefile("rb")

    def send(self, conn, reader, data):
        if isinstance(data, str):
            data = (data + "\n").encode()
        conn.sendall(data)
        return reader.readline().decode().strip()

    def test_round_trip(self):
        conn, reader = self.connect()
        with conn:
            self.assertEqual(self.send(conn, reader, "SET city Nashville"), "OK")
            self.assertEqual(self.send(conn, reader, "GET city"), "VALUE Nashville")
            self.assertEqual(self.send(conn, reader, 'SET motto "keep it simple"'), "OK")
            self.assertEqual(self.send(conn, reader, "GET motto"), "VALUE keep it simple")
            self.assertEqual(self.send(conn, reader, "QUIT"), "BYE")

    def test_bad_bytes_do_not_drop_the_connection(self):
        conn, reader = self.connect()
        with conn:
            self.assertEqual(self.send(conn, reader, b"SET k \xff\xfe\n"), "ERROR command must be UTF-8 text")
            self.assertEqual(self.send(conn, reader, "PING"), "PONG")  # same connection still works

    def test_line_too_long(self):
        conn, reader = self.connect()
        with conn:
            huge = b"SET big " + b"x" * (MAX_LINE + 10) + b"\n"
            self.assertEqual(self.send(conn, reader, huge), "ERROR line too long")

    def test_server_survives_abrupt_disconnect(self):
        conn, _ = self.connect()
        conn.sendall(b"SET a 1\n")
        # SO_LINGER with 0 seconds makes close() send a hard reset instead of a polite goodbye
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        conn.close()
        time.sleep(0.1)
        conn, reader = self.connect()
        with conn:
            self.assertEqual(self.send(conn, reader, "PING"), "PONG")


if __name__ == "__main__":
    unittest.main()
