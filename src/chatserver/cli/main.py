"""CLI entry points. Argument wiring lives here; each command's behavior lives
in ``chatserver.cli.commands`` and calls the library API."""

from __future__ import annotations

import argparse

from chatserver.cli.commands import admin as admin_cmd
from chatserver.cli.commands import client as client_cmd
from chatserver.cli.commands import demo as demo_cmd
from chatserver.cli.commands import server as server_cmd
from chatserver.persistence.migrations import init_db


def build_server_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chatserver")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-db", help="create or migrate the SQLite schema")
    init.add_argument("--db", default="chat.db")

    server_cmd.add_serve_parser(sub)
    admin_cmd.add_admin_parser(sub)
    demo_cmd.add_demo_parser(sub)
    return parser


def server_main(argv: list[str] | None = None) -> int:
    args = build_server_parser().parse_args(argv)
    if args.command == "init-db":
        init_db(args.db)
        print(f"initialized SQLite schema at {args.db}")
        return 0
    if args.command == "serve":
        return server_cmd.serve(args)
    if args.command == "admin":
        return admin_cmd.admin(args)
    if args.command == "demo":
        return demo_cmd.demo(args)
    return 2  # unreachable: subparsers are required


def client_main(argv: list[str] | None = None) -> int:
    return client_cmd.client_main(argv)
