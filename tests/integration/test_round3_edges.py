""" Test round 3 edges """

from __future__ import annotations

import json
import socket
import time

from chatserver.protocol.framing import FrameDecoder, encode_frame
from conftest import connect_raw, read_system_containing, read_until, running_server, send_frame


def test_leave_removes_membership_and_notifies_room(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(alice, {"type": "join", "room": "general"})
        send_frame(bob, {"type": "join", "room": "general"})
        read_until(alice, "history")
        read_until(bob, "history")

        send_frame(alice, {"type": "leave", "room": "general"})
        notice = read_system_containing(bob, "alice left general")
        assert notice["room"] == "general"

        send_frame(alice, {"type": "chat", "room": "general", "body": "ghost"})
        error = read_until(alice, "error")
        assert error["code"] == "room_not_found"
        assert server.rooms.counts().get("general", 0) == 1


def test_rename_rate_limited_after_handshake(tmp_path) -> None:
    with running_server(tmp_path, rate_limit_messages=2, rate_limit_window=60.0) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "hello", "nick": "alice2"})
        read_until(alice, "welcome")
        send_frame(alice, {"type": "hello", "nick": "alice3"})
        read_until(alice, "welcome")
        send_frame(alice, {"type": "hello", "nick": "alice4"})
        error = read_until(alice, "error")
        assert error["code"] == "rate_limited"
        assert server.nicks.get("alice3") is not None


def test_history_limit_clamped_to_config(tmp_path) -> None:
    with running_server(tmp_path, history_limit=3) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        for i in range(5):
            send_frame(alice, {"type": "chat", "room": "general", "body": f"m{i}"})
            read_until(alice, "chat")
        send_frame(alice, {"type": "history", "room": "general", "limit": 100})
        history = read_until(alice, "history")
        assert len(history["messages"]) == 3


def test_wire_history_without_room_uses_general_default(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        send_frame(alice, {"type": "chat", "room": "general", "body": "stored"})
        read_until(alice, "chat")

        send_frame(alice, {"type": "join", "room": "other"})
        read_until(alice, "history")

        send_frame(alice, {"type": "history", "limit": 10})
        history = read_until(alice, "history")
        assert history["room"] == "general"
        assert any(item["body"] == "stored" for item in history["messages"])


def test_join_sends_history_before_system_notice(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        decoder = FrameDecoder(1 << 20)
        types: list[str] = []
        deadline = time.monotonic() + 3.0
        while len(types) < 2 and time.monotonic() < deadline:
            data = alice.recv(65536)
            frames, _errors = decoder.feed(data)
            for frame in frames:
                types.append(json.loads(frame).get("type", ""))
        assert types[:2] == ["history", "system"]


def test_frame_too_large_over_socket(tmp_path) -> None:
    with running_server(tmp_path, max_message_size=64) as server:
        sock = socket.create_connection(server.address, timeout=2.0)
        sock.settimeout(2.0)
        send_frame(sock, {"type": "hello", "nick": "alice"})
        read_until(sock, "welcome")
        sock.sendall(b"x" * 128 + b"\n")
        error = read_until(sock, "error")
        assert error["code"] == "frame_too_large"
