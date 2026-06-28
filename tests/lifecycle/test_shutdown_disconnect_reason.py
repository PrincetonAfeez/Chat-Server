""" Test shutdown disconnect reason """

from __future__ import annotations

import time

from conftest import connect_raw, running_server


def test_idle_client_shutdown_records_server_shutdown_reason(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        assert server.snapshot()["connected_clients"] == 1
        server.stopping.set()
        deadline = time.monotonic() + 5.0
        while server.snapshot()["connected_clients"] > 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        reasons = [item["reason"] for item in server.recent_evictions]
        disconnect_events = []
        conn = server.store.connect()
        try:
            rows = conn.execute(
                "SELECT details_json FROM events WHERE event_type = 'disconnect' ORDER BY id DESC LIMIT 5"
            ).fetchall()
            import json

            for row in rows:
                details = json.loads(row[0])
                disconnect_events.append(details.get("reason"))
        finally:
            conn.close()
        assert "SERVER_SHUTDOWN" in disconnect_events or any("SERVER_SHUTDOWN" in r for r in reasons)
