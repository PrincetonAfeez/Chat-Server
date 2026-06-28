""" Test protocol edges """

from __future__ import annotations

import json

from chatserver.protocol.framing import encode_frame
from chatserver.queues.db_jobs import DbJob
from conftest import connect_raw, read_system_containing, read_until, running_server, send_frame


def test_presence_returns_who_response(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        send_frame(alice, {"type": "presence", "room": "general"})
        who = read_until(alice, "who")
        assert who["users"] == ["alice"]
        assert who["room"] == "general"


def test_chat_without_join_returns_room_not_found(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "chat", "room": "general", "body": "hi"})
        error = read_until(alice, "error")
        assert error["code"] == "room_not_found"


def test_history_without_join_returns_room_not_found(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "history", "room": "general", "limit": 5})
        error = read_until(alice, "error")
        assert error["code"] == "room_not_found"


def test_dm_to_offline_user_returns_user_not_found(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "dm", "to": "ghost", "body": "hello?"})
        error = read_until(alice, "error")
        assert error["code"] == "user_not_found"


def test_rejoin_sends_already_in_ack(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        send_frame(alice, {"type": "join", "room": "general"})
        notice = read_system_containing(alice, "already in general")
        assert notice["room"] == "general"


def test_system_notice_broadcast_when_db_persist_rejected(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        bob = connect_raw(server, "bob")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        send_frame(bob, {"type": "join", "room": "general"})
        read_until(bob, "history")
        original = server.enqueue_db

        def reject_persist(job: DbJob) -> bool:
            if job.job_type == "persist_system_message":
                return False
            return original(job)

        server.enqueue_db = reject_persist  # type: ignore[method-assign]
        carol = connect_raw(server, "carol")
        send_frame(carol, {"type": "join", "room": "general"})
        read_until(carol, "history")
        notice = read_system_containing(alice, "carol joined general")
        assert notice["room"] == "general"
        cached = server.history_cache.get("general") or []
        assert not any("carol joined general" in item.get("body", "") for item in cached)


def test_pending_messages_merge_on_history_cache_miss(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        send_frame(alice, {"type": "chat", "room": "general", "body": "durable"})
        read_until(alice, "chat")

        original_store = server.store.store_message

        def slow_store(conn, message):  # type: ignore[no-untyped-def]
            if message.get("body") == "pending":
                import time

                time.sleep(0.4)
            return original_store(conn, message)

        server.store.store_message = slow_store  # type: ignore[method-assign]
        server.history_cache.clear()
        server.history_cache.append = lambda room, message: None  # type: ignore[method-assign, assignment]
        send_frame(alice, {"type": "chat", "room": "general", "body": "pending"})
        send_frame(alice, {"type": "history", "room": "general", "limit": 10})
        history = read_until(alice, "history")
        bodies = [item["body"] for item in history["messages"]]
        assert "durable" in bodies
        assert "pending" in bodies
