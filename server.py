"""
server.py - puts the cache on the network.

Other programs connect over TCP (the same protocol the web uses under HTTP)
and send one text command per line:

    SET <key> <value> [ttl_seconds]   ->  OK
    GET <key>                          ->  VALUE <value>   or   NOT_FOUND
    DEL <key>                          ->  DELETED          or   NOT_FOUND
    SIZE                               ->  SIZE <number>
    PING                               ->  PONG
    QUIT                               ->  BYE (and the connection closes)

Put quotes around a value that has spaces:   SET greeting "hello world" 60

Each client gets its own thread, so several clients can talk to the
server at the same time. The cache's lock keeps the data safe.

Run it:   python server.py --port 6380 --capacity 100
"""

import argparse
import shlex
import socket
import threading

from cache import LRUCache

MAX_LINE = 64 * 1024  # longest command we accept, so one client can't eat all the memory


def split_command(line):
    """Split a line into words, keeping "quoted text" together as one word.

    Backslashes are kept as normal characters (so C:\\temp stays C:\\temp),
    and # is not treated as a comment.
    """
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True  # split only on spaces, not on punctuation
    lexer.commenters = ""          # '#' is a normal character
    lexer.escape = ""              # '\' is a normal character
    return list(lexer)


def handle_command(cache, line):
    """Turn one line of text into a reply. Kept separate so it is easy to test."""
    try:
        parts = split_command(line)
    except ValueError:  # e.g. a quote that is never closed
        return "ERROR unclosed quote"
    if not parts:
        return "ERROR empty command"

    command = parts[0].upper()   # commands are not case-sensitive
    args = parts[1:]

    if command == "PING":
        return "PONG"

    if command == "SET":
        if len(args) not in (2, 3):
            return 'ERROR usage: SET <key> <value> [ttl_seconds] (quote values with spaces: "like this")'
        key, value = args[0], args[1]
        ttl = None
        if len(args) == 3:
            try:
                ttl = float(args[2])
            except ValueError:
                return 'ERROR ttl must be a number (if your value has spaces, put it in quotes: "like this")'
        try:
            cache.set(key, value, ttl)
        except ValueError as error:
            return f"ERROR {error}"
        return "OK"

    if command == "GET":
        if len(args) != 1:
            return "ERROR usage: GET <key>"
        value = cache.get(args[0])
        return "NOT_FOUND" if value is None else f"VALUE {value}"

    if command == "DEL":
        if len(args) != 1:
            return "ERROR usage: DEL <key>"
        return "DELETED" if cache.delete(args[0]) else "NOT_FOUND"

    if command == "SIZE":
        return f"SIZE {cache.size()}"

    return f"ERROR unknown command {command}"


def serve_client(conn, address, cache):
    """Talk to one connected client until it says QUIT or disconnects."""
    with conn:
        reader = conn.makefile("rb")  # read raw bytes line by line; we decode each line ourselves
        try:
            while True:
                raw = reader.readline(MAX_LINE + 1)
                if not raw:  # the client closed the connection
                    break
                if len(raw) > MAX_LINE and not raw.endswith(b"\n"):
                    # The rest of this huge line is still coming, so we can't
                    # find where the next command starts. Say why, then hang up.
                    conn.sendall(b"ERROR line too long\n")
                    break
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    conn.sendall(b"ERROR command must be UTF-8 text\n")
                    continue
                if line.strip().upper() == "QUIT":
                    conn.sendall(b"BYE\n")
                    break
                reply = handle_command(cache, line)
                conn.sendall((reply + "\n").encode("utf-8"))
        except OSError:
            # The client vanished mid-conversation (reset, broken pipe...).
            # Nothing to answer, so just let this thread end quietly.
            pass


def run_server(host="127.0.0.1", port=6380, capacity=100):
    cache = LRUCache(capacity=capacity)
    # AF_INET = IPv4 address, SOCK_STREAM = TCP (reliable, in-order bytes)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # restart without "address in use"
        server.bind((host, port))   # claim the address and port
        server.listen()             # start waiting for connections
        print(f"Mini cache listening on {host}:{port} (capacity {capacity})")
        while True:
            conn, address = server.accept()  # wait for the next client
            thread = threading.Thread(target=serve_client, args=(conn, address, cache), daemon=True)
            thread.start()                   # handle it in the background


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mini in-memory cache server")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 inside Docker or on a VM")
    parser.add_argument("--port", type=int, default=6380)
    parser.add_argument("--capacity", type=int, default=100)
    options = parser.parse_args()
    run_server(options.host, options.port, options.capacity)
