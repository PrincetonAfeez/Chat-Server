from __future__ import annotations

from chatserver.cache.history_cache import HistoryCache
from chatserver.scheduling.clock import ManualClock


def test_history_cache_bounds_messages_and_rooms() -> None:
    clock = ManualClock()
    cache = HistoryCache(max_rooms=1, messages_per_room=2, ttl_seconds=100, clock=clock)
    cache.append("general", {"body": "one"})
    cache.append("general", {"body": "two"})
    cache.append("general", {"body": "three"})
    assert [m["body"] for m in cache.get("general") or []] == ["two", "three"]

    cache.append("random", {"body": "four"})
    assert cache.get("general") is None
    assert cache.evictions == 1


def test_history_cache_ttl_eviction() -> None:
    clock = ManualClock()
    cache = HistoryCache(max_rooms=2, messages_per_room=2, ttl_seconds=5, clock=clock)
    cache.append("general", {"body": "one"})
    clock.advance(6)
    assert cache.get("general") is None
    assert cache.evictions == 1
