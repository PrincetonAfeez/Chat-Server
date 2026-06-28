""" Test client commands """

from __future__ import annotations

import io
from unittest.mock import MagicMock

from chatserver.network.client import ChatClient


def test_leave_defers_current_room_until_system_notice() -> None:
    client = ChatClient(host="127.0.0.1", port=9000, nick="alice", output=io.StringIO())
    client.sock = MagicMock()
    client.current_room = "general"
    client._send_command("/leave general")
    assert client.current_room == "general"
    assert client._pending_leave_room == "general"
    client._track_server_message({"type": "system", "room": "general", "body": "alice left general"})
    assert client.current_room is None
    assert client._pending_leave_room is None


def test_nick_defers_local_nick_until_welcome() -> None:
    client = ChatClient(host="127.0.0.1", port=9000, nick="alice", output=io.StringIO())
    client.sock = MagicMock()
    sent: list[dict] = []
    client.send = lambda message: sent.append(message)  # type: ignore[method-assign, assignment]
    client._send_command("/nick bob")
    assert client.nick == "alice"
    assert client._pending_nick == "bob"
    client._track_server_message({"type": "welcome", "nick": "bob"})
    assert client.nick == "bob"
    assert client._pending_nick is None


def test_nick_error_clears_pending_without_changing_nick() -> None:
    client = ChatClient(host="127.0.0.1", port=9000, nick="alice", output=io.StringIO())
    client.sock = MagicMock()
    client._pending_nick = "bob"
    client._track_server_message({"type": "error", "code": "nick_taken", "message": "taken"})
    assert client.nick == "alice"
    assert client._pending_nick is None


def test_connect_error_surfaces_server_message() -> None:
    client = ChatClient(host="127.0.0.1", port=9000, nick="alice", output=io.StringIO())
    client._track_server_message(
        {"type": "error", "code": "nick_taken", "message": "Nickname is already active", "recoverable": False}
    )
    assert client._connect_error == "nick_taken: Nickname is already active"


def test_connect_error_surfaces_handshake_server_busy() -> None:
    client = ChatClient(host="127.0.0.1", port=9000, nick="alice", output=io.StringIO())
    client._track_server_message(
        {
            "type": "error",
            "code": "server_busy",
            "message": "Database writer backlog is full",
            "recoverable": False,
        }
    )
    assert client._connect_error == "server_busy: Database writer backlog is full"


def test_rate_limited_error_keeps_pending_join() -> None:
    client = ChatClient(host="127.0.0.1", port=9000, nick="alice", output=io.StringIO())
    client.sock = MagicMock()
    client._pending_join_room = "general"
    client._track_server_message(
        {"type": "error", "code": "rate_limited", "message": "slow down", "recoverable": True}
    )
    assert client._pending_join_room == "general"


def test_history_limit_only_uses_current_room_after_ack() -> None:
    client = ChatClient(host="127.0.0.1", port=9000, nick="alice", output=io.StringIO())
    client.sock = MagicMock()
    client.current_room = "general"
    sent: list[dict] = []
    client.send = lambda message: sent.append(message)  # type: ignore[method-assign, assignment]
    assert client._send_command("/history 25")
    assert sent == [{"type": "history", "room": "general", "limit": 25}]


def test_history_without_current_room_requires_explicit_room() -> None:
    output = io.StringIO()
    client = ChatClient(host="127.0.0.1", port=9000, nick="alice", output=output)
    client.sock = MagicMock()
    client.current_room = None
    sent: list[dict] = []
    client.send = lambda message: sent.append(message)  # type: ignore[method-assign, assignment]
    assert client._send_command("/history")
    assert sent == []
    assert "join a room first" in output.getvalue()
