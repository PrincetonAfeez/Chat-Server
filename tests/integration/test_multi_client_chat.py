from __future__ import annotations

from conftest import connect_raw, read_until, running_server, send_frame


def test_multi_client_room_chat(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(alice, {"type": "join", "room": "general"})
        send_frame(bob, {"type": "join", "room": "general"})
        read_until(alice, "system")
        read_until(bob, "system")
        send_frame(alice, {"type": "chat", "room": "general", "body": "hello bob"})
        message = read_until(bob, "chat")
        assert message["sender"] == "alice"
        assert message["body"] == "hello bob"
        assert message["message_id"].startswith("m_")


def test_direct_message(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(alice, {"type": "dm", "to": "bob", "body": "secret"})
        message = read_until(bob, "dm")
        assert message["sender"] == "alice"
        assert message["to"] == "bob"
        assert message["body"] == "secret"


def test_dms_are_not_persisted(tmp_path) -> None:
    import time

    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(alice, {"type": "dm", "to": "bob", "body": "private"})
        read_until(bob, "dm")
        # Let the DB writer drain; DMs are live-only, so nothing lands in messages.
        deadline = time.monotonic() + 3.0
        while server.db_writer.backlog() > 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.store.db_stats()["messages"] == 0


def test_history_on_join_comes_from_cache(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "system")
        send_frame(alice, {"type": "chat", "room": "general", "body": "cached hello"})
        read_until(alice, "chat")

        bob = connect_raw(server, "bob")
        send_frame(bob, {"type": "join", "room": "general"})
        history = read_until(bob, "history")
        assert any(item["body"] == "cached hello" for item in history["messages"])
