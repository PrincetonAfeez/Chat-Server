from __future__ import annotations

import socket
import time
from typing import Any

from chatserver.protocol.framing import FrameDecoder, encode_frame
from conftest import connect_raw, running_server


def _admin(server, request: dict[str, Any]) -> dict[str, Any]:
    host, port = server.admin_address
    with socket.create_connection((host, port), timeout=5.0) as sock:
        sock.sendall(encode_frame(request))
        decoder = FrameDecoder(1 << 20)
        sock.settimeout(5.0)
        while True:
            data = sock.recv(65536)
            if not data:
                raise AssertionError("admin socket closed without a response")
            frames, _errors = decoder.feed(data)
            if frames:
                import json

                return json.loads(frames[0])


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_admin_socket_reports_stats_and_kicks(tmp_path) -> None:
    with running_server(tmp_path, admin_enabled=True, admin_port=0) as server:
        assert server.admin_address is not None
        _alice = connect_raw(server, "alice")
        assert _wait_until(lambda: server.snapshot()["connected_clients"] == 1)

        stats = _admin(server, {"command": "stats"})
        assert stats["ok"] is True
        assert stats["result"]["connected_clients"] == 1

        evictions = _admin(server, {"command": "evictions"})
        assert evictions["ok"] is True
        assert "recent_evictions" in evictions["result"]

        kicked = _admin(server, {"command": "kick", "nick": "alice"})
        assert kicked["ok"] is True
        assert kicked["result"]["kicked"] is True
        assert _wait_until(lambda: server.snapshot()["connected_clients"] == 0)

        bad = _admin(server, {"command": "nonsense"})
        assert bad["ok"] is False


def test_admin_broadcast_reaches_clients(tmp_path) -> None:
    with running_server(tmp_path, admin_enabled=True, admin_port=0) as server:
        alice = connect_raw(server, "alice")
        result = _admin(server, {"command": "broadcast", "message": "server restart soon"})
        assert result["ok"] is True

        decoder = FrameDecoder(1 << 20)
        alice.settimeout(3.0)
        import json

        got = None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and got is None:
            data = alice.recv(65536)
            if not data:
                break
            frames, _errors = decoder.feed(data)
            for frame in frames:
                message = json.loads(frame)
                if message.get("type") == "system" and "restart" in message.get("body", ""):
                    got = message
        assert got is not None
