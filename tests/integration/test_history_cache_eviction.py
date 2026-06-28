""" Test history cache eviction """

from __future__ import annotations

import time

from chatserver.cache.history_cache import HistoryCache
from chatserver.protocol.messages import new_message_id, utc_timestamp
from chatserver.scheduling.clock import ManualClock
from conftest import connect_raw, read_until, running_server, send_frame


def test_post_eviction_history_reloads_from_sqlite(tmp_path) -> None:
    with running_server(tmp_path, cache_ttl=1.0, room_cache_messages=50) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        for i in range(5):
            send_frame(alice, {"type": "chat", "room": "general", "body": f"m{i}"})
            read_until(alice, "chat")

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if any(m["body"] == "m4" for m in server.store.recent_room_messages("general", 50)):
                break
            time.sleep(0.02)

        server.history_cache.cleanup_expired()
        send_frame(alice, {"type": "chat", "room": "general", "body": "after-evict"})
        read_until(alice, "chat")

        send_frame(alice, {"type": "history", "room": "general", "limit": 10})
        history = read_until(alice, "history")
        bodies = [item["body"] for item in history["messages"]]
        assert "m0" in bodies
        assert "after-evict" in bodies


def test_history_cache_incomplete_after_ttl_is_miss() -> None:
    clock = ManualClock()
    cache = HistoryCache(max_rooms=2, messages_per_room=10, ttl_seconds=5, clock=clock)
    cache.warm("general", [{"message_id": "m1", "body": "one"}])
    clock.advance(6)
    cache.cleanup_expired()
    cache.append("general", {"message_id": "m2", "body": "two"})
    assert cache.get("general") is None


def test_merge_message_lists_deduplicates_by_id() -> None:
    message = {"message_id": "m1", "body": "one"}
    merged = HistoryCache.merge_message_lists([message], [dict(message, body="dup")])
    assert len(merged) == 1
