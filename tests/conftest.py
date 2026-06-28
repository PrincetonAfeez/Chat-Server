""" Conftest for the chat server library """

from __future__ import annotations

import json
import socket
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from chatserver.config import ServerConfig
from chatserver.network.server import ChatServer
from chatserver.protocol.framing import FrameDecoder, encode_frame

# Test directories that spin up real sockets / use timing; auto-marked `slow`
# so `pytest -m "not slow"` runs the pure-unit suite in well under a second.
_SLOW_DIRS = {"concurrency", "integration", "lifecycle", "admin"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _SLOW_DIRS & set(item.path.parts):
            item.add_marker(pytest.mark.slow)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    import threading
    import warnings

    leaked = [
        t.name
        for t in threading.enumerate()
        if t.name.startswith(("chatserver-", "chatclient-")) and t.is_alive() and t is not threading.main_thread()
    ]
    if leaked and exitstatus == 0:
        warnings.warn(
            f"non-daemon threads still alive at exit: {leaked}",
            stacklevel=1,
        )


@contextmanager
def running_server(tmp_path: Path, **overrides: Any) -> Iterator[ChatServer]:
    data = {
        "host": "127.0.0.1",
        "port": 0,
        "db_path": str(tmp_path / "chat.db"),
        "heartbeat_interval": 1000.0,
        "idle_timeout": 5000.0,
    }
    data.update(overrides)
    server = ChatServer(ServerConfig(**data))
    server.start()
    try:
        yield server
    finally:
        server.stop()


def connect_raw(server: ChatServer, nick: str | None = None) -> socket.socket:
    sock = socket.create_connection(server.address, timeout=2.0)
    sock.settimeout(2.0)
    if nick:
        send_frame(sock, {"type": "hello", "nick": nick})
        read_until(sock, "welcome")
    return sock


def send_frame(sock: socket.socket, message: dict[str, Any]) -> None:
    sock.sendall(encode_frame(message))


def read_until(sock: socket.socket, msg_type: str) -> dict[str, Any]:
    # Generous inbound buffer, like a real client: server-aggregated frames
    # (history bundles) can exceed the per-message send cap.
    decoder = FrameDecoder(1 << 20)
    while True:
        data = sock.recv(65536)
        if not data:
            raise AssertionError("socket closed before expected frame")
        frames, errors = decoder.feed(data)
        assert not errors
        for frame in frames:
            message = json.loads(frame)
            if message.get("type") == msg_type:
                return message


def read_system_containing(sock: socket.socket, text: str, *, timeout: float = 3.0) -> dict[str, Any]:
    decoder = FrameDecoder(1 << 20)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = sock.recv(65536)
        if not data:
            raise AssertionError("socket closed before expected frame")
        frames, errors = decoder.feed(data)
        assert not errors
        for frame in frames:
            message = json.loads(frame)
            if message.get("type") == "system" and text in message.get("body", ""):
                return message
    raise AssertionError(f"no system frame containing {text!r}")
