"""Demonstrates how direct SQLite writes from handlers couple I/O to the network."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from chatserver.observability.stats import ServerStats
from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.persistence.writer import DbWriter
from chatserver.queues.db_jobs import DbJob


def demonstrate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        # Direct model: the "network handler" performs the SQLite write itself,
        # so the handler thread is blocked for the full duration of disk I/O.
        direct_store = SQLiteStore(Path(tmp) / "direct.db")
        direct_store.initialize()
        conn = direct_store.connect()
        direct_blocking_writes = 0
        try:
            for i in range(5):
                direct_store.create_room(conn, f"room{i}")
                conn.commit()
                direct_blocking_writes += 1
        finally:
            conn.close()

        # Queued model: the handler only enqueues; one background writer thread
        # serializes the disk work off the hot path.
        stats = ServerStats()
        queued_store = SQLiteStore(Path(tmp) / "queued.db")
        writer = DbWriter(queued_store, maxsize=100, stats=stats)
        writer.start()
        try:
            enqueued = sum(writer.enqueue(DbJob("create_room", {"room": f"room{i}"})) for i in range(5))
        finally:
            writer.stop(drain=True)
            writer.join(5.0)

        return {
            "direct_writes_blocking_handler": direct_blocking_writes,
            "queued_jobs_handed_off": enqueued,
            "queued_writes_completed_by_worker": stats.snapshot()["db_write_successes"],
            "lesson": "network handlers enqueue DB jobs; a single writer thread owns the disk I/O.",
        }


def unsafe_example() -> str:
    result = demonstrate()
    return (
        "Unsafe direct-DB demo: the direct model blocked the handler on "
        f"{result['direct_writes_blocking_handler']} synchronous SQLite writes, while the queued model "
        f"handed off {result['queued_jobs_handed_off']} jobs and a background writer completed "
        f"{result['queued_writes_completed_by_worker']}. {result['lesson']}"
    )
