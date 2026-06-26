""" Shutdown module for the chat server library """

from __future__ import annotations

import signal
from collections.abc import Callable
from threading import Lock
from types import FrameType

_stop_lock = Lock()
_stop_requested = False


def install_signal_handlers(stop: Callable[[], None]) -> None:
    global _stop_requested

    with _stop_lock:
        _stop_requested = False

    def handler(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        global _stop_requested
        with _stop_lock:
            if _stop_requested:
                return
            _stop_requested = True
        stop()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handler)
