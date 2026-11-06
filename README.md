# Mini Cache Server

A small in-memory key-value cache server in Python, like a tiny version of Redis.
Other programs connect over TCP and store or read data with simple text commands.
When it is full, it removes the **least recently used** key, and keys can **expire** after a set time.

Built with only Python's standard library: no extra installs needed.

## What it does

```
SET <key> <value> [ttl_seconds]   ->  OK
GET <key>                          ->  VALUE <value>   or   NOT_FOUND
DEL <key>                          ->  DELETED          or   NOT_FOUND
SIZE                               ->  SIZE <number>
PING                               ->  PONG
QUIT                               ->  BYE
```

Values with spaces go in quotes: `SET greeting "hello world" 60`.
Bad input never crashes a connection: it gets an `ERROR ...` reply instead.

Example session (capacity 2):

```
> SET a 1          OK
> SET b 2          OK
> GET a            VALUE 1      (a is now the most recently used)
> SET c 3          OK           (cache is full, so b is evicted)
> GET b            NOT_FOUND
> SET temp hi 1    OK           (expires in 1 second)
> GET temp         VALUE hi
  ...1 second later...
> GET temp         NOT_FOUND
```

## How to run it

```bash
# 1. Start the server (terminal 1)
python server.py --port 6380 --capacity 100

# 2. Talk to it (terminal 2)
python client.py --port 6380

# 3. Run the tests
python -m unittest -v
```

With Docker:

```bash
docker build -t mini-cache .
docker run -p 6380:6380 mini-cache
python client.py --port 6380
```

## How it works

| File | What it does |
| --- | --- |
| `cache.py` | The LRU cache: a hash map plus a doubly linked list, with expiry and a lock |
| `server.py` | A TCP socket server; one thread per client; turns text commands into cache calls |
| `client.py` | A small terminal client for typing commands |
| `test_cache.py` | 17 tests: LRU order, eviction, expiry, errors, quoted values, 10 threads at once, and real network tests (round trip, bad bytes, oversized lines, abrupt disconnects) |
| `Dockerfile` | Packages the server to run anywhere, including an OCI VM |

### Why a hash map AND a linked list?

- The **hash map** (Python `dict`) finds any key in **O(1)** time.
- The **doubly linked list** keeps keys in order of use: newest at the front, oldest at the back.
  Moving a key to the front or removing the oldest only changes a few pointers, also **O(1)**.
- Together: `get`, `set` and `delete` are all **O(1)**. A list alone would need O(n) to find a key;
  a dict alone can't tell you which key is the oldest without scanning.

### Other design choices

- **Dummy head and tail nodes** so the list is never empty, which removes edge-case checks.
- **A lock** around every cache operation, because each client runs on its own thread.
- **Lazy expiry**: an expired key is removed when someone reads it (or when `SIZE` runs),
  instead of running a background timer.
- **`time.monotonic()`** for expiry, because it can't jump backward if the system clock changes.
- **`handle_command` is separate from the socket code**, so commands can be tested without a network.
- **Quoted values** are parsed with Python's `shlex`, with backslashes and `#` kept as normal characters,
  so `SET path C:\temp` stores exactly `C:\temp`.
- **Defensive connection handling**: invalid UTF-8 gets an error reply, lines over 64 KB are refused,
  and a client that drops its connection is cleaned up quietly instead of printing a traceback.

### Known tradeoff

Because expiry is lazy, an expired key that nobody has read still takes a slot. If the cache is full,
a new key evicts the least recently used key, even if an expired key is still sitting there.
Fixing that cheaply needs a background cleanup thread or a second structure ordered by expiry time.

## Deploy on OCI Always Free (optional)

1. Create an Oracle Cloud Free Tier account.
2. Create a compute instance (Always Free shape, for example Ampere A1) with Oracle Linux or Ubuntu.
3. SSH in, install Docker, copy this folder, then `docker build` and `docker run -p 6380:6380 mini-cache`.
4. In the VCN security list, allow inbound TCP on port 6380, only from your own IP address.
5. From your laptop: `python client.py --host <VM public IP> --port 6380`.

Only open the port to your own IP: this server has no password.

## Ideas to extend it

- Save data to disk so it survives a restart (persistence)
- Add a password (`AUTH` command)
- Split keys across several servers (sharding with consistent hashing)
- Copy data to a second server (replication)
