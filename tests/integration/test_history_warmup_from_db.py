from __future__ import annotations

import time

from conftest import connect_raw, read_until, running_server, send_frame


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_cache_miss_warms_recent_history_from_sqlite(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "system")
        send_frame(alice, {"type": "chat", "room": "general", "body": "durable hello"})
        read_until(alice, "chat")

        # Wait until the chat is durably persisted, then blow away the in-memory
        # cache to force the next join to warm from SQLite.
        assert _wait_until(
            lambda: any(m["body"] == "durable hello" for m in server.store.recent_room_messages("general", 50))
        )
        warmups_before = server.snapshot()["cache"]["warmups"]
        server.history_cache.clear()

        bob = connect_raw(server, "bob")
        send_frame(bob, {"type": "join", "room": "general"})
        history = read_until(bob, "history")
        assert any(item["body"] == "durable hello" for item in history["messages"])
        assert server.snapshot()["cache"]["warmups"] > warmups_before


def test_small_history_request_does_not_underfill_cache(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "system")
        for i in range(10):
            send_frame(alice, {"type": "chat", "room": "general", "body": f"m{i}"})
            read_until(alice, "chat")

        # Wait for durability, then cold the cache so the next read warms from DB.
        assert _wait_until(
            lambda: len([m for m in server.store.recent_room_messages("general", 50) if m["sender"] == "alice"]) == 10
        )
        server.history_cache.clear()

        # A small /history request must NOT under-fill the cache.
        send_frame(alice, {"type": "history", "room": "general", "limit": 2})
        small = read_until(alice, "history")
        assert len(small["messages"]) == 2

        # A subsequent full-window request still returns the full window.
        send_frame(alice, {"type": "history", "room": "general", "limit": 50})
        full = read_until(alice, "history")
        chat_bodies = [m["body"] for m in full["messages"] if m.get("sender") == "alice"]
        assert len(chat_bodies) == 10
