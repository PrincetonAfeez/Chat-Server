"""Demonstrates registry corruption when threads share state without a lock 

This mirrors the real hazard in a chat server: one thread broadcasts by
iterating a room's member set while another thread joins/leaves and mutates it.
Without a lock the iteration raises ``RuntimeError: Set changed size during
iteration``; the safe version snapshots under a lock first.
"""

from __future__ import annotations

import sys
from threading import Event, Lock, Thread
from typing import Any


def _provoke_unsynchronized_error(rounds: int) -> str | None:
    shared: set[int] = set(range(64))
    keep_mutating = Event()
    keep_mutating.set()

    def mutate() -> None:
        i = 64
        while keep_mutating.is_set():
            shared.add(i)
            shared.discard(i - 32)
            i += 1

    # These operations are individually fast, so with the default ~5ms thread
    # switch interval the GIL rarely preempts mid-iteration. Shorten the
    # interval for the demo so the race surfaces reliably, then restore it.
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    mutator = Thread(target=mutate, daemon=True)
    mutator.start()
    try:
        for _ in range(rounds):
            try:
                for _member in shared:  # no lock: races with mutate()
                    pass
            except RuntimeError as exc:
                return str(exc)
    finally:
        keep_mutating.clear()
        mutator.join(1.0)
        sys.setswitchinterval(previous_interval)
    return None


def _safe_iteration(rounds: int) -> str | None:
    shared: set[int] = set(range(64))
    lock = Lock()
    keep_mutating = Event()
    keep_mutating.set()

    def mutate() -> None:
        i = 64
        while keep_mutating.is_set():
            with lock:
                shared.add(i)
                shared.discard(i - 32)
            i += 1

    mutator = Thread(target=mutate, daemon=True)
    mutator.start()
    try:
        for _ in range(rounds):
            try:
                with lock:
                    snapshot = list(shared)  # safe: copy under the lock, iterate the copy
                for _member in snapshot:
                    pass
            except RuntimeError as exc:
                return str(exc)
    finally:
        keep_mutating.clear()
        mutator.join(1.0)
    return None


def demonstrate(rounds: int = 4000, attempts: int = 25) -> dict[str, Any]:
    naive_error: str | None = None
    for _ in range(attempts):
        naive_error = _provoke_unsynchronized_error(rounds)
        if naive_error is not None:
            break
    safe_error = _safe_iteration(rounds)
    return {
        "naive_iteration_error": naive_error,
        "safe_iteration_error": safe_error,
        "lesson": "protect shared registries with a lock and broadcast from a snapshot.",
    }


def unsafe_example() -> str:
    result = demonstrate()
    naive = result["naive_iteration_error"] or "no error observed this run"
    return (
        "Unsafe no-locks demo: broadcasting over a room set while another thread mutated it raised "
        f"[{naive}], while snapshotting under a lock iterated cleanly "
        f"(error: {result['safe_iteration_error']}). {result['lesson']}"
    )
