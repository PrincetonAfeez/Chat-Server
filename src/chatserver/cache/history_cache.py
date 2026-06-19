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
    ) -> None:
        self.max_rooms = max_rooms
        self.messages_per_room = messages_per_room
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._lock = RLock()
        self._rooms: OrderedDict[str, CachedRoom] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.warmups = 0

    def append(self, room: str, message: dict[str, Any]) -> None:
        with self._lock:
            entry = self._rooms.get(room)
            if entry is None:
                entry = CachedRoom(deque(maxlen=self.messages_per_room), self.clock())
                self._rooms[room] = entry
            entry.messages.append(message)
            entry.touched_at = self.clock()
            self._rooms.move_to_end(room)
            self._evict_if_needed()

    def get(self, room: str) -> list[dict[str, Any]] | None:
        with self._lock:
            self._cleanup_expired_locked()
            entry = self._rooms.get(room)
            if entry is None:
                self.misses += 1
                return None
            entry.touched_at = self.clock()
            self._rooms.move_to_end(room)
            self.hits += 1
            return list(entry.messages)

    def warm(self, room: str, messages: list[dict[str, Any]]) -> None:
        with self._lock:
            self._rooms[room] = CachedRoom(
                deque(messages[-self.messages_per_room :], maxlen=self.messages_per_room),
                self.clock(),
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

    def _cleanup_expired_locked(self) -> int:
        if self.ttl_seconds <= 0:
            return 0
        cutoff = self.clock() - self.ttl_seconds
        expired = [room for room, entry in list(self._rooms.items()) if entry.touched_at < cutoff]
        for room in expired:
            self._rooms.pop(room, None)
            self.evictions += 1
        return len(expired)

    def _evict_if_needed(self) -> None:
        while len(self._rooms) > self.max_rooms:
            self._rooms.popitem(last=False)
            self.evictions += 1
