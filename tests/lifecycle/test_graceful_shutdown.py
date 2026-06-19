from __future__ import annotations

from conftest import connect_raw, running_server


def test_graceful_shutdown_clears_registries(tmp_path) -> None:
    with running_server(tmp_path) as server:
        _sock = connect_raw(server, "alice")
        assert server.snapshot()["connected_clients"] == 1
        server.stop()
        snapshot = server.snapshot()
        assert snapshot["connected_clients"] == 0
        assert snapshot["rooms"] == {}
