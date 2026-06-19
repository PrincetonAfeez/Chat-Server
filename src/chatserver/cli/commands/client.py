"""`chatclient connect` — the interactive CLI client entry point."""

from __future__ import annotations

import argparse

from chatserver.network.client import ChatClient


def client_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chatclient")
    sub = parser.add_subparsers(dest="command", required=True)
    connect = sub.add_parser("connect", help="connect to a chat server")
    connect.add_argument("--host", default="127.0.0.1")
    connect.add_argument("--port", type=int, default=9000)
    connect.add_argument("--nick", required=True)
    args = parser.parse_args(argv)
    if args.command == "connect":
        client = ChatClient(host=args.host, port=args.port, nick=args.nick)
        return client.run_interactive()
    return 2
