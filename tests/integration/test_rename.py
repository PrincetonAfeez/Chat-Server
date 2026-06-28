""" Test rename """

from __future__ import annotations

from conftest import connect_raw, read_system_containing, read_until, running_server, send_frame


def test_rename_updates_nick_and_notifies_room(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(alice, {"type": "join", "room": "general"})
        send_frame(bob, {"type": "join", "room": "general"})
        read_until(alice, "system")
        read_until(bob, "system")

        send_frame(alice, {"type": "hello", "nick": "alice2"})
        read_until(alice, "welcome")
        notice = read_system_containing(bob, "renamed to alice2")
        assert "alice renamed to alice2" in notice["body"]


def test_rename_collision_is_rejected(tmp_path) -> None:
    with running_server(tmp_path) as server:
        _alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(bob, {"type": "hello", "nick": "alice"})
        error = read_until(bob, "error")
        assert error["code"] == "nick_taken"


def test_handshake_nick_collision_on_connect(tmp_path) -> None:
    with running_server(tmp_path) as server:
        _alice = connect_raw(server, "alice")
        second = connect_raw(server)
        send_frame(second, {"type": "hello", "nick": "alice"})
        error = read_until(second, "error")
        assert error["code"] == "nick_taken"
