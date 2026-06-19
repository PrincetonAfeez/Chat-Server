from __future__ import annotations

import socket
import time

from chatserver.config import ServerConfig
from chatserver.network.server import ChatServer
from chatserver.scheduling.clock import ManualClock


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_silent_connection_is_evicted_after_handshake_timeout(tmp_path) -> None:
    # A peer that connects but never sends hello must not hold a slot + threads
    # forever (anti-slowloris). Driven by an injected clock, no real waiting.
    clock = ManualClock()
    server = ChatServer(
        ServerConfig(
            host="127.0.0.1",
            port=0,
            db_path=str(tmp_path / "chat.db"),
            heartbeat_interval=1000.0,
            idle_timeout=5000.0,
            handshake_timeout=10.0,
        ),
        clock=clock,
    )
    server.start()
    try:
        sock = socket.create_connection(server.address, timeout=2.0)
        try:
            assert _wait_until(lambda: server.snapshot()["connected_clients"] == 1)
            clock.advance(11.0)
            server.evict_idle_sessions()
            assert _wait_until(lambda: server.snapshot()["connected_clients"] == 0)
            snap = server.snapshot()
            assert snap["handshake_timeouts"] == 1
            assert any(e["reason"] == "HANDSHAKE_TIMED_OUT" for e in snap["recent_evictions"])
        finally:
            sock.close()
    finally:
        server.stop()
