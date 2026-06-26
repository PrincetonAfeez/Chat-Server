""" Rate limit module for the chat server library """

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from threading import Lock
from time import monotonic


class RateLimiter:
    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.clock = clock
        self._events: deque[float] = deque()
        self._lock = Lock()

    def allow(self) -> bool:
        with self._lock:
            now = self.clock()
            cutoff = now - self.window_seconds
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            if len(self._events) >= self.max_events:
                return False
            self._events.append(now)
            return True

    @property
    def count(self) -> int:
        with self._lock:
            now = self.clock()
            cutoff = now - self.window_seconds
            while self._events and self._events[0] <= cutoff:
                self._events.popleft()
            return len(self._events)
