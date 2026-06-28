""" Test no thread leak """

from __future__ import annotations

import threading
import time

from conftest import connect_raw, running_server, send_frame


def _server_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("chatserver-") and t.is_alive()]


def test_shutdown_leaves_no_worker_or_client_threads(tmp_path) -> None:
    # Enable the admin socket too, so its thread is covered by the leak check.
    with running_server(tmp_path, admin_enabled=True, admin_port=0) as server:
        alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(alice, {"type": "join", "room": "general"})
        send_frame(bob, {"type": "join", "room": "general"})
        # Reader, writer, accept, scheduler, db-writer, and admin threads are live.
        assert _server_threads(), "expected live server threads while running"
        assert any(t.name == "chatserver-admin" for t in _server_threads()), "admin thread should be live"
        server.stop()

    # Give any just-joined threads a beat to settle, then assert none survive.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and _server_threads():
        time.sleep(0.05)
    leaked = [t.name for t in _server_threads()]
    assert leaked == [], f"threads leaked after shutdown: {leaked}"
