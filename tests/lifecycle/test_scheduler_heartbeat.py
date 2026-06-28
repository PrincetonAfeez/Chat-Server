""" Test scheduler heartbeat """

from __future__ import annotations

import time

from chatserver.config import ServerConfig
from chatserver.network.server import ChatServer
from chatserver.scheduling.clock import ManualClock
from conftest import connect_raw, send_frame


def test_matching_pong_prevents_idle_eviction_via_scheduler(tmp_path) -> None:
    clock = ManualClock()
    server = ChatServer(
        ServerConfig(
            host="127.0.0.1",
            port=0,
            db_path=str(tmp_path / "chat.db"),
            heartbeat_interval=1.0,
            idle_timeout=5.0,
        ),
        clock=clock,
    )
    server.start()
    try:
        alice = connect_raw(server, "alice")
        assert server.snapshot()["connected_clients"] == 1
        clock.advance(1.1)
        server.scheduler.run_pending()
        with server.lock:
            session = next(iter(server.sessions.values()))
            nonce = session.last_ping_nonce
        assert nonce is not None
        send_frame(alice, {"type": "pong", "nonce": nonce})
        deadline = time.monotonic() + 2.0
        while session.last_pong_at <= session.created_at and time.monotonic() < deadline:
            time.sleep(0.01)
        clock.advance(4.0)
        server.scheduler.run_pending()
        assert server.snapshot()["connected_clients"] == 1
        assert server.snapshot()["idle_timeout_evictions"] == 0
    finally:
        server.stop()
