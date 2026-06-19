from __future__ import annotations

import logging
import sqlite3
from collections import deque
from itertools import count
from queue import Empty, Full, PriorityQueue
from threading import Event, Lock, Thread
from typing import Any

from chatserver.observability.events import DB_JOB_ENQUEUE, DB_JOB_FAILURE, DB_JOB_SUCCESS
from chatserver.observability.logging import get_logger, log_event
from chatserver.observability.stats import ServerStats
from chatserver.queues.db_jobs import DbJob

from .sqlite_store import SQLiteStore

# Errors that are worth retrying (the database was transiently busy/locked).
# Anything else (a malformed job, a programming error) is permanent and is
# logged and dropped without burning retry attempts.
TRANSIENT_DB_ERRORS = (sqlite3.OperationalError,)
MAX_ATTEMPTS = 3
QueueItem = tuple[int, int, DbJob]


class DbWriter:
    """Single background writer that serializes all SQLite writes.

    Jobs are processed highest-priority-first (higher ``DbJob.priority`` wins),
    with FIFO ordering within a priority band. The queue is bounded; when it is
    full ``enqueue`` returns False so callers can apply their backpressure
    policy (the server rejects new chat with ``server_busy`` by default).
    """

    def __init__(self, store: SQLiteStore, *, maxsize: int, stats: ServerStats) -> None:
        self.store = store
        self.stats = stats
        self.queue: PriorityQueue[QueueItem] = PriorityQueue(maxsize=maxsize)
        self._stop = Event()
        self._thread: Thread | None = None
        self._seq = count()
        self._seq_lock = Lock()
        self.failures: deque[dict[str, Any]] = deque(maxlen=200)
        self._logger = get_logger("chatserver.db")

    def start(self) -> None:
        self.store.initialize()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="chatserver-db-writer", daemon=False)
        self._thread.start()

    def _next_seq(self) -> int:
        with self._seq_lock:
            return next(self._seq)

    def _put(self, job: DbJob) -> bool:
        # PriorityQueue pops the smallest tuple first, so negate priority to make
        # the highest-priority job come out first; seq breaks ties as FIFO.
        item: QueueItem = (-job.priority, self._next_seq(), job)
        try:
            self.queue.put_nowait(item)
        except Full:
            return False
        return True

    def enqueue(self, job: DbJob) -> bool:
        if not self._put(job):
            self.stats.incr("db_jobs_dropped")
            return False
        self.stats.incr("db_jobs_enqueued")
        log_event(
            self._logger,
            DB_JOB_ENQUEUE,
            level=logging.DEBUG,
            job_id=job.job_id,
            job_type=job.job_type,
            priority=job.priority,
        )
        return True

    def backlog(self) -> int:
        return self.queue.qsize()

    def stop(self, *, drain: bool = True) -> None:
        if not drain:
            while True:
                try:
                    self.queue.get_nowait()
                except Empty:
                    break
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        conn = self.store.connect()
        try:
            while not self._stop.is_set() or not self.queue.empty():
                try:
                    _, _, job = self.queue.get(timeout=0.1)
                except Empty:
                    continue
                self._process(conn, job)
        finally:
            conn.close()

    def _process(self, conn: sqlite3.Connection, job: DbJob) -> None:
        try:
            self._apply_job(conn, job)
            conn.commit()
            self.stats.incr("db_write_successes")
            log_event(
                self._logger,
                DB_JOB_SUCCESS,
                level=logging.DEBUG,
                job_id=job.job_id,
                job_type=job.job_type,
            )
        except TRANSIENT_DB_ERRORS as exc:
            conn.rollback()
            job.attempts += 1
            job.last_error = str(exc)
            # Re-queue for retry via _put (not enqueue) so a retry is not counted
            # as a brand-new enqueue.
            if job.attempts < MAX_ATTEMPTS and self._put(job):
                return
            self._record_failure(job)
        except Exception as exc:  # noqa: BLE001 - permanent failure, never retry
            conn.rollback()
            job.attempts += 1
            job.last_error = str(exc)
            self._record_failure(job)

    def _record_failure(self, job: DbJob) -> None:
        self.failures.append(job.summary())
        self.stats.incr("db_write_failures")
        log_event(
            self._logger,
            DB_JOB_FAILURE,
            job_id=job.job_id,
            job_type=job.job_type,
            attempts=job.attempts,
            error=job.last_error,
        )

    def _apply_job(self, conn: sqlite3.Connection, job: DbJob) -> None:
        payload = job.payload
        if job.job_type == "store_message":
            self.store.store_message(conn, payload["message"])
            return
        if job.job_type == "upsert_user":
            self.store.upsert_user(conn, payload["nick"])
            return
        if job.job_type == "create_room":
            self.store.create_room(conn, payload["room"])
            return
        if job.job_type == "record_join":
            self.store.record_event(conn, "join", nick=payload.get("nick"), room=payload.get("room"))
            return
        if job.job_type == "record_leave":
            self.store.record_event(conn, "leave", nick=payload.get("nick"), room=payload.get("room"))
            return
        if job.job_type == "record_disconnect":
            self.store.record_event(conn, "disconnect", nick=payload.get("nick"), details=payload)
            return
        if job.job_type == "record_eviction":
            self.store.record_event(conn, "eviction", nick=payload.get("nick"), details=payload)
            return
        if job.job_type == "prune_history":
            self.store.prune_history(conn, payload["keep_count"], room=payload.get("room"))
            return
        if job.job_type == "store_system_event":
            self.store.record_event(
                conn,
                payload.get("event_type", "system"),
                nick=payload.get("nick"),
                room=payload.get("room"),
                details=payload.get("details"),
            )
            return
        raise ValueError(f"unknown DB job type: {job.job_type}")
