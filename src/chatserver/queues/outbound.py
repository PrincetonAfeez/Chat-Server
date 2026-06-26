""" Outbound queue for the chat server library """

from __future__ import annotations

import contextlib
from queue import Empty, Full, Queue
from threading import Lock
from typing import Any


class OutboundQueue:
    """Bounded per-client send buffer.

    The writer thread is the only consumer; producers are routing/broadcast
    calls on other threads. Each underlying Queue operation is atomic, which is
    all the policies below rely on.
    """

    def __init__(self, maxsize: int) -> None:
        self._queue: Queue[dict[str, Any]] = Queue(maxsize=maxsize)
        self._lock = Lock()

    def put_nowait(self, message: dict[str, Any]) -> bool:
        try:
            self._queue.put_nowait(message)
        except Full:
            return False
        return True

    def put_drop_oldest(self, message: dict[str, Any]) -> bool:
        """Make room by discarding the oldest queued message, then enqueue."""
        with self._lock:
            if self.put_nowait(message):
                return True
            with contextlib.suppress(Empty):
                self._queue.get_nowait()
            return self.put_nowait(message)

    def get(self, timeout: float | None = None) -> dict[str, Any]:
        return self._queue.get(timeout=timeout)

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()
