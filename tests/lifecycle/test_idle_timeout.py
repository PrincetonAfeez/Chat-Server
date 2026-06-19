from __future__ import annotations

from chatserver.config import ServerConfig
from chatserver.network.server import ChatServer
from chatserver.scheduling.clock import ManualClock
from conftest import connect_raw


def test_idle_timeout_evicts_without_sleep(tmp_path) -> None:
    clock = ManualClock()
    server = ChatServer(
        ServerConfig(
            host="127.0.0.1",
            port=0,
            db_path=str(tmp_path / "chat.db"),
            heartbeat_interval=1000.0,
            idle_timeout=10.0,
        ),
        clock=clock,
    )
    server.start()
    try:
        _sock = connect_raw(server, "alice")
        assert server.snapshot()["connected_clients"] == 1
        clock.advance(11.0)
        server.evict_idle_sessions()
        assert server.snapshot()["connected_clients"] == 0
        assert server.snapshot()["idle_timeout_evictions"] == 1
    finally:
        server.stop()
