from __future__ import annotations

import signal
from collections.abc import Callable
from types import FrameType


def install_signal_handlers(stop: Callable[[], None]) -> None:
    def handler(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        stop()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
