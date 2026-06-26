""" History cache for the chat server library """

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Any


@dataclass(slots=True)
class CachedRoom:
    messages: deque[dict[str, Any]]
    touched_at: float
    # False after TTL/LRU eviction until warm() reloads from SQLite.
    complete: bool = True


class HistoryCache:
    """Bounded in-memory room history cache.

    Shared by every session reader thread (append/get/warm) and the scheduler
    thread (cleanup_expired), so all access is guarded by a single RLock. The
    cache is never the durable source of truth: SQLite holds durable history and
    warms the cache on a miss.
    """

    def __init__(
        self,
        *,
        max_rooms: int,
        messages_per_room: int,
        ttl_seconds: float,
        clock: Callable[[], float] = monotonic,
        on_evict: Callable[[int], None] | None = None,
    ) -> None:
        self.max_rooms = max_rooms
        self.messages_per_room = messages_per_room
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._on_evict = on_evict
        self._lock = RLock()
        self._rooms: OrderedDict[str, CachedRoom] = OrderedDict()
        self._evicted_rooms: set[str] = set()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.warmups = 0

    def append(self, room: str, message: dict[str, Any]) -> None:
        with self._lock:
            entry = self._rooms.get(room)
            if entry is None:
                complete = room not in self._evicted_rooms
                entry = CachedRoom(deque(maxlen=self.messages_per_room), self.clock(), complete=complete)
                self._rooms[room] = entry
                self._evicted_rooms.discard(room)
            entry.messages.append(message)
            entry.touched_at = self.clock()
            self._rooms.move_to_end(room)
            self._evict_if_needed()

    def get(self, room: str) -> list[dict[str, Any]] | None:
        with self._lock:
            self._cleanup_expired_locked()
            entry = self._rooms.get(room)
            if entry is None or not entry.complete:
                self.misses += 1
                return None
            entry.touched_at = self.clock()
            self._rooms.move_to_end(room)
            self.hits += 1
            return list(entry.messages)

    def warm(self, room: str, messages: list[dict[str, Any]]) -> None:
        with self._lock:
            existing = list(self._rooms[room].messages) if room in self._rooms else []
            merged = self._merge_messages(messages, existing)
            self._evicted_rooms.discard(room)
            self._rooms[room] = CachedRoom(
                deque(merged[-self.messages_per_room :], maxlen=self.messages_per_room),
                self.clock(),
                complete=True,
            )
            self._rooms.move_to_end(room)
            self.warmups += 1
            self._evict_if_needed()

    def cleanup_expired(self) -> int:
        """Evict rooms whose TTL has lapsed. Returns the number evicted."""
        with self._lock:
            return self._cleanup_expired_locked()

    def clear(self) -> None:
        """Drop all cached rooms (e.g. to model a cold cache after a restart)."""
        with self._lock:
            self._rooms.clear()
            self._evicted_rooms.clear()

    def invalidate_all(self) -> None:
        """Mark every cached room stale so the next read re-loads from SQLite."""
        with self._lock:
            for room in list(self._rooms):
                self._evicted_rooms.add(room)
            self._rooms.clear()

    def apply_retention(self, keep_count: int) -> None:
        """Trim cached rooms and mark them stale after a DB prune."""
        with self._lock:
            for room, entry in list(self._rooms.items()):
                if len(entry.messages) > keep_count:
                    entry.messages = deque(
                        list(entry.messages)[-keep_count:],
                        maxlen=self.messages_per_room,
                    )
                entry.complete = False
                self._evicted_rooms.add(room)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "rooms": len(self._rooms),
                "messages": sum(len(entry.messages) for entry in self._rooms.values()),
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "warmups": self.warmups,
            }

    def remove_message(self, room: str, message_id: str) -> None:
        with self._lock:
            entry = self._rooms.get(room)
            if entry is None:
                return
            kept = [item for item in entry.messages if item.get("message_id") != message_id]
            entry.messages = deque(kept, maxlen=self.messages_per_room)

    @staticmethod
    def merge_message_lists(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge history sources in order, deduplicating by message_id."""
        seen: set[tuple[str, ...]] = set()
        merged: list[dict[str, Any]] = []
        for group in groups:
            for message in group:
                key = HistoryCache._dedup_key(message)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(message)
        return merged

    @staticmethod
    def _dedup_key(message: dict[str, Any]) -> tuple[str, ...]:
        message_id = message.get("message_id")
        if isinstance(message_id, str):
            return ("id", message_id)
        sender = message.get("sender", "")
        body = message.get("body", "")
        timestamp = message.get("server_timestamp", "")
        return ("fallback", str(message.get("kind", "")), str(sender), str(body), str(timestamp))

    def _merge_messages(self, *groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.merge_message_lists(*groups)

    def _cleanup_expired_locked(self) -> int:
        if self.ttl_seconds <= 0:
            return 0
        cutoff = self.clock() - self.ttl_seconds
        expired = [room for room, entry in list(self._rooms.items()) if entry.touched_at < cutoff]
        for room in expired:
            self._rooms.pop(room, None)
            self._evicted_rooms.add(room)
            self.evictions += 1
        if expired and self._on_evict:
            self._on_evict(len(expired))
        return len(expired)

    def _evict_if_needed(self) -> None:
        evicted = 0
        while len(self._rooms) > self.max_rooms:
            room, _entry = self._rooms.popitem(last=False)
            self._evicted_rooms.add(room)
            self.evictions += 1
            evicted += 1
        if evicted and self._on_evict:
            self._on_evict(evicted)
