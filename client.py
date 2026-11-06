"""
client.py - a tiny program to talk to the cache server from your terminal.

Run the server first, then:   python client.py --port 6380
Type commands like:  SET name Niki   SET msg "hello world" 60   GET name   DEL name   SIZE   QUIT
"""

import argparse
import socket
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6380)
    options = parser.parse_args()

    try:
        conn = socket.create_connection((options.host, options.port), timeout=5)
    except OSError as error:
        sys.exit(f"Could not connect to {options.host}:{options.port} ({error}). Is the server running?")
    conn.settimeout(None)  # once connected, wait as long as needed for replies

    with conn:
        reader = conn.makefile("r", encoding="utf-8")
        print("Connected. Type a command (QUIT to exit).")
        while True:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                line = "QUIT"
            try:
                conn.sendall((line + "\n").encode("utf-8"))  # send one line
                reply = reader.readline()                    # wait for one line back
            except OSError:
                reply = ""
            if not reply:  # empty means the server closed the connection
                print("Connection closed by the server.")
                break
            reply = reply.strip()
            print(reply)
            if reply == "BYE":
                break


if __name__ == "__main__":
    main()
