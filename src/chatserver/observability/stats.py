""" Stats module for the chat server library """

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from typing import Any

# Window over which messages/sec is measured, so the rate reflects *current*
# throughput rather than a lifetime average that only ever decays.
RATE_WINDOW_SECONDS = 60.0


@dataclass
class ServerStats:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _message_times: deque[float] = field(default_factory=deque, init=False, repr=False)
    started_at: float = field(default_factory=monotonic)
    connected_clients: int = 0
    active_rooms: int = 0
    total_messages_accepted: int = 0
    rejected_messages: int = 0
    dropped_messages: int = 0
    evicted_clients: int = 0
    slow_client_evictions: int = 0
    idle_timeout_evictions: int = 0
    handshake_timeouts: int = 0
    rate_limit_rejections: int = 0
    db_write_successes: int = 0
    db_write_failures: int = 0
    db_jobs_enqueued: int = 0
    db_jobs_dropped: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_evictions: int = 0
    cache_warmups: int = 0
    scheduler_ticks: int = 0

    def incr(self, field_name: str, amount: int = 1) -> None:
        with self._lock:
            setattr(self, field_name, getattr(self, field_name) + amount)

    def set_gauge(self, field_name: str, value: int) -> None:
        with self._lock:
            setattr(self, field_name, value)

    def mark_message(self) -> None:
        """Record an accepted message for the cumulative count and rolling rate."""
        now = monotonic()
        with self._lock:
            self.total_messages_accepted += 1
            self._message_times.append(now)
            self._prune_locked(now)

    def _prune_locked(self, now: float) -> None:
        cutoff = now - RATE_WINDOW_SECONDS
        times = self._message_times
        while times and times[0] < cutoff:
            times.popleft()

    def snapshot(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            now = monotonic()
            self._prune_locked(now)
            uptime = now - self.started_at
            window = min(RATE_WINDOW_SECONDS, max(uptime, 0.001))
            data: dict[str, Any] = {
                "uptime": uptime,
                "connected_clients": self.connected_clients,
                "active_rooms": self.active_rooms,
                "total_messages_accepted": self.total_messages_accepted,
                "messages_per_sec": len(self._message_times) / window,
                "rejected_messages": self.rejected_messages,
                "dropped_messages": self.dropped_messages,
                "evicted_clients": self.evicted_clients,
                "slow_client_evictions": self.slow_client_evictions,
                "idle_timeout_evictions": self.idle_timeout_evictions,
                "handshake_timeouts": self.handshake_timeouts,
                "rate_limit_rejections": self.rate_limit_rejections,
                "db_write_successes": self.db_write_successes,
                "db_write_failures": self.db_write_failures,
                "db_jobs_enqueued": self.db_jobs_enqueued,
                "db_jobs_dropped": self.db_jobs_dropped,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
                "cache_evictions": self.cache_evictions,
                "cache_warmups": self.cache_warmups,
                "scheduler_ticks": self.scheduler_ticks,
            }
            if extra:
                data.update(extra)
            return data
