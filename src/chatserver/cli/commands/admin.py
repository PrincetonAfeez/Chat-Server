"""`chatserver admin …` — drive a running server's control socket, or read the DB offline."""

from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path
from typing import Any

from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.protocol.framing import FrameDecoder, decode_json_frame, encode_frame

LIVE_ONLY = {"clients", "queues", "cache", "evictions", "kick", "broadcast"}


def add_admin_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    admin = sub.add_parser("admin", help="inspect a running server or the DB")
    admin_sub = admin.add_subparsers(dest="admin_command", required=True)
    for name in ["stats", "rooms", "clients", "queues", "cache", "evictions"]:
        _add_endpoint_args(admin_sub.add_parser(name))
    kick = admin_sub.add_parser("kick")
    kick.add_argument("--nick", required=True)
    _add_endpoint_args(kick)
    broadcast = admin_sub.add_parser("broadcast")
    broadcast.add_argument("--message", required=True)
    _add_endpoint_args(broadcast)


def _add_endpoint_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="admin control socket host")
    parser.add_argument("--port", type=int, help="admin control socket port (live server)")
    parser.add_argument("--db", default="chat.db", help="DB path for offline stats/rooms when --port is omitted")
    parser.add_argument("--format", choices=["json", "table"], default="json", help="output format")


def admin(args: argparse.Namespace) -> int:
    if args.port is not None:
        request: dict[str, Any] = {"command": args.admin_command}
        if args.admin_command == "kick":
            request["nick"] = args.nick
        elif args.admin_command == "broadcast":
            request["message"] = args.message
        try:
            response = _admin_request(args.host, args.port, request)
        except OSError as exc:
            print(f"could not reach admin socket at {args.host}:{args.port}: {exc}")
            return 1
        if not response.get("ok"):
            print(json.dumps(response, indent=2, sort_keys=True))
            return 1
        _emit(response.get("result", response), args.format)
        return 0

    if args.admin_command in LIVE_ONLY:
        print(f"'admin {args.admin_command}' needs a live server: pass --port (serve with --admin-port)")
        return 2

    # Offline fallback: read durable counts straight from the DB.
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"database not found: {db_path}")
        return 1
    store = SQLiteStore(db_path)
    if args.admin_command == "stats":
        _emit(store.db_stats(), args.format)
        return 0
    if args.admin_command == "rooms":
        # Offline: durable room names + stored message counts (not live member counts).
        _emit(store.rooms(), args.format)
        return 0
    return 2


def _admin_request(host: str, port: int, request: dict[str, Any]) -> dict[str, Any]:
    with socket.create_connection((host, port), timeout=5.0) as sock:
        sock.sendall(encode_frame(request))
        decoder = FrameDecoder(1 << 20)
        sock.settimeout(5.0)
        while True:
            data = sock.recv(65536)
            if not data:
                raise OSError("admin connection closed before a response was received")
            frames, _errors = decoder.feed(data)
            if frames:
                return decode_json_frame(frames[0])


def _emit(result: Any, fmt: str) -> None:
    if fmt == "table":
        print(_render_table(result))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


def _render_table(result: Any) -> str:
    """Render a flat dict or a list of dicts as an aligned text table."""
    if isinstance(result, dict):
        if not result:
            return "(empty)"
        width = max(len(str(k)) for k in result)
        lines = []
        for key in sorted(result):
            value = result[key]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True)
            lines.append(f"{str(key).ljust(width)}  {value}")
        return "\n".join(lines)
    if isinstance(result, list):
        if not result:
            return "(none)"
        if all(isinstance(row, dict) for row in result):
            columns: list[str] = []
            for row in result:
                for key in row:
                    if key not in columns:
                        columns.append(key)
            widths = {c: max(len(c), *(len(str(row.get(c, ""))) for row in result)) for c in columns}
            header = "  ".join(c.ljust(widths[c]) for c in columns)
            sep = "  ".join("-" * widths[c] for c in columns)
            body = "\n".join("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns) for row in result)
            return f"{header}\n{sep}\n{body}"
        return "\n".join(str(item) for item in result)
    return str(result)
