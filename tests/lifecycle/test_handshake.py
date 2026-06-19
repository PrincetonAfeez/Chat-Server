from __future__ import annotations

from conftest import connect_raw, read_until, running_server, send_frame


def test_pre_handshake_chat_gets_error(tmp_path) -> None:
    with running_server(tmp_path) as server:
        sock = connect_raw(server)
        send_frame(sock, {"type": "chat", "room": "general", "body": "too soon"})
        error = read_until(sock, "error")
        assert error["code"] == "unauthorized"


def test_max_connections_rejects_extra_client(tmp_path) -> None:
    with running_server(tmp_path, max_connections=1) as server:
        _first = connect_raw(server, "alice")
        second = connect_raw(server)
        error = read_until(second, "error")
        assert error["code"] == "server_full"


def test_duplicate_nick_is_rejected_with_structured_error(tmp_path) -> None:
    with running_server(tmp_path) as server:
        _first = connect_raw(server, "alice")
        second = connect_raw(server)
        send_frame(second, {"type": "hello", "nick": "alice"})
        error = read_until(second, "error")
        assert error["code"] == "nick_taken"
        assert error["recoverable"] is False
