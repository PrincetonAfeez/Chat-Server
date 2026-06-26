"""Demonstrates leaked worker threads when shutdown is not explicit """

from __future__ import annotations

from threading import Event, Thread
from typing import Any


def demonstrate() -> dict[str, Any]:
    # No stop path: the worker loops on a flag nothing ever sets, so "shutting
    # down" the program leaves the thread running.
    missing_stop = Event()

    def runaway() -> None:
        while not missing_stop.is_set():
            missing_stop.wait(0.02)

    leaked = Thread(target=runaway, daemon=True)
    leaked.start()
    leaked_alive_after_shutdown = leaked.is_alive()
    missing_stop.set()  # clean up the demo's own thread after observing the leak
    leaked.join(1.0)

    # Safe: a shared stop Event plus join() guarantees the worker is gone.
    stop = Event()

    def worker() -> None:
        while not stop.wait(0.02):
            pass

    safe = Thread(target=worker)
    safe.start()
    stop.set()
    safe.join(1.0)

    return {
        "leaked_thread_alive_after_shutdown": leaked_alive_after_shutdown,
        "safe_thread_alive_after_shutdown": safe.is_alive(),
        "lesson": "share one stop Event and join() every worker so nothing survives shutdown.",
    }


def unsafe_example() -> str:
    result = demonstrate()
    return (
        "Unsafe shutdown demo: a worker with no stop path was still alive after shutdown "
        f"({result['leaked_thread_alive_after_shutdown']}), while a worker with a stop Event and join() "
        f"was gone ({not result['safe_thread_alive_after_shutdown']}). {result['lesson']}"
    )
