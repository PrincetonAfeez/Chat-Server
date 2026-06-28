""" Test shutdown protocol edges """

from __future__ import annotations

import socket
import time

from chatserver.protocol.framing import encode_frame
from conftest import connect_raw, read_until, running_server, send_frame


def test_server_shutting_down_error_on_late_frame(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        server.stopping.set()
        send_frame(alice, {"type": "chat", "room": "general", "body": "late"})
        error = read_until(alice, "error")
        assert error["code"] == "server_shutting_down"


def test_fatal_framing_sets_protocol_error_state(tmp_path) -> None:
    with running_server(tmp_path, max_message_size=64) as server:
        sock = socket.create_connection(server.address, timeout=2.0)
        sock.settimeout(2.0)
        send_frame(sock, {"type": "hello", "nick": "alice"})
        read_until(sock, "welcome")
        session = next(iter(server.sessions.values()))
        sock.sendall(b"x" * 128 + b"\n")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and session.state.value == "ACTIVE":
            time.sleep(0.02)
        assert session.state.value == "PROTOCOL_ERROR"


def test_post_close_frames_in_same_batch_are_ignored(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        server.stopping.set()
        batch = encode_frame({"type": "chat", "room": "general", "body": "one"}) + encode_frame(
            {"type": "join", "room": "secret"}
        )
        alice.sendall(batch)
        time.sleep(0.2)
        assert "secret" not in server.rooms.room_names()
