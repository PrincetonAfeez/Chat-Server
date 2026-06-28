""" Test graceful shutdown """

from __future__ import annotations

import json

from chatserver.protocol.framing import FrameDecoder
from conftest import connect_raw, read_until, running_server, send_frame


def test_graceful_shutdown_clears_registries(tmp_path) -> None:
    with running_server(tmp_path) as server:
        _sock = connect_raw(server, "alice")
        assert server.snapshot()["connected_clients"] == 1
        server.stop()
        snapshot = server.snapshot()
        assert snapshot["connected_clients"] == 0
        assert snapshot["rooms"] == {}


def test_graceful_shutdown_notifies_connected_client(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        server.stop()
        decoder = FrameDecoder(1 << 20)
        saw_shutdown = False
        alice.settimeout(1.0)
        try:
            while True:
                data = alice.recv(65536)
                if not data:
                    break
                frames, _errors = decoder.feed(data)
                for frame in frames:
                    message = json.loads(frame)
                    if message.get("type") == "system" and "shutting down" in message.get("body", ""):
                        saw_shutdown = True
                        break
                if saw_shutdown:
                    break
        except OSError:
            pass
        assert saw_shutdown
