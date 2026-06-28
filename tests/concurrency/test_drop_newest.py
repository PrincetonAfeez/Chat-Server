""" Test drop newest """

from __future__ import annotations

import socket
import time

from chatserver.config import ServerConfig
from chatserver.network.server import ChatServer
from conftest import connect_raw, send_frame


def test_drop_newest_keeps_connection_alive(tmp_path) -> None:
    server = ChatServer(
        ServerConfig(
            host="127.0.0.1",
            port=0,
            db_path=str(tmp_path / "chat.db"),
            outbound_queue_size=1,
            outbound_backpressure_policy="drop_newest",
            heartbeat_interval=1000.0,
            idle_timeout=5000.0,
        )
    )
    server.start()
    try:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        # Fill the outbound queue without reading: send chat while queue holds prior frames.
        send_frame(alice, {"type": "chat", "room": "general", "body": "one"})
        send_frame(alice, {"type": "chat", "room": "general", "body": "two"})
        deadline = time.monotonic() + 2.0
        while server.snapshot()["dropped_messages"] < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.snapshot()["dropped_messages"] >= 1
        assert server.snapshot()["connected_clients"] == 1
        assert server.snapshot()["slow_client_evictions"] == 0
    finally:
        server.stop()
