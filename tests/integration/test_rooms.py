""" Test rooms and who """

from __future__ import annotations

from conftest import connect_raw, read_until, running_server, send_frame


def test_rooms_and_who(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "system")

        send_frame(alice, {"type": "rooms"})
        rooms = read_until(alice, "rooms")
        assert rooms["rooms"] == [{"room": "general", "members": 1}]

        send_frame(alice, {"type": "who", "room": "general"})
        who = read_until(alice, "who")
        assert who["users"] == ["alice"]
