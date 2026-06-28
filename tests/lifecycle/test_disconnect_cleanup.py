""" Test disconnect cleanup """

from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable
from typing import Any

from chatserver.protocol.framing import FrameDecoder
from conftest import connect_raw, running_server, send_frame


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _read_matching(sock: socket.socket, predicate: Callable[[dict[str, Any]], bool], timeout: float = 5.0):
    decoder = FrameDecoder(1 << 20)
    sock.settimeout(0.3)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = sock.recv(65536)
        except TimeoutError:
            continue
        if not data:
            return None
        for frame in decoder.feed(data)[0]:
            message = json.loads(frame)
            if predicate(message):
                return message
    return None


def test_disconnect_removes_session_from_all_registries(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(alice, {"type": "join", "room": "general"})
        send_frame(bob, {"type": "join", "room": "general"})
        assert _wait_until(lambda: server.snapshot()["connected_clients"] == 2)

        # Hard-drop alice's socket; the server must detect the closed read and
        # clean up rooms, the nick registry, and the session registry.
        alice.close()

        assert _wait_until(lambda: server.snapshot()["connected_clients"] == 1)
        snap = server.snapshot()
        assert snap["rooms"].get("general") == 1  # only bob remains
        with server.lock:
            assert "alice" not in server.nicks
            assert all(s.nick != "alice" for s in server.sessions.values())

        # bob is told that alice left (ignore join/history frames, match on content).
        notice = _read_matching(
            bob,
            lambda m: m.get("type") == "system" and "alice" in m.get("body", "") and "left" in m.get("body", ""),
        )
        assert notice is not None, "bob should receive an 'alice left' system notice"
