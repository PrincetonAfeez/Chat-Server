""" Writer for the chat server library """

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict, deque
from itertools import count
from queue import Empty, Full, PriorityQueue
from collections.abc import Callable
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

    def __init__(
        self,
        store: SQLiteStore,
        *,
        maxsize: int,
        stats: ServerStats,
        on_job_failure: Callable[[DbJob], None] | None = None,
        on_job_success: Callable[[DbJob], None] | None = None,
    ) -> None:
        self.store = store
        self.stats = stats
        self.queue: PriorityQueue[QueueItem] = PriorityQueue(maxsize=maxsize)
        self._stop = Event()
        self._thread: Thread | None = None
        self._seq = count()
        self._seq_lock = Lock()
        self._pending_lock = Lock()
        self._pending_by_room: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.failures: deque[dict[str, Any]] = deque(maxlen=200)
        self._logger = get_logger("chatserver.db")
        self._drain_on_stop = True
        self._on_job_failure = on_job_failure
        self._on_job_success = on_job_success

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

    def _track_pending(self, job: DbJob) -> None:
        if job.job_type not in ("store_message", "persist_system_message"):
            return
        message = job.payload.get("message")
        if not isinstance(message, dict):
            return
        room = message.get("room")
        if isinstance(room, str):
            with self._pending_lock:
                self._pending_by_room[room].append(message)

    def _untrack_pending(self, job: DbJob) -> None:
        if job.job_type not in ("store_message", "persist_system_message"):
            return
        message = job.payload.get("message")
        room = message.get("room") if isinstance(message, dict) else None
        message_id = message.get("message_id") if isinstance(message, dict) else None
        if not isinstance(room, str) or not isinstance(message_id, str):
            return
        with self._pending_lock:
            pending = self._pending_by_room.get(room)
            if not pending:
                return
            self._pending_by_room[room] = [item for item in pending if item.get("message_id") != message_id]
            if not self._pending_by_room[room]:
                del self._pending_by_room[room]

    def pending_room_messages(self, room: str) -> list[dict[str, Any]]:
        with self._pending_lock:
            return list(self._pending_by_room.get(room, ()))

    def _put(self, job: DbJob, *, track: bool = True) -> bool:
        if self._stop.is_set():
            return False
        # PriorityQueue pops the smallest tuple first, so negate priority to make
        # the highest-priority job come out first; seq breaks ties as FIFO.
        item: QueueItem = (-job.priority, self._next_seq(), job)
        try:
            self.queue.put_nowait(item)
        except Full:
            return False
        if track:
            self._track_pending(job)
        return True

    def enqueue(self, job: DbJob) -> bool:
        if self._stop.is_set() and (self._thread is None or not self._thread.is_alive()):
            return False
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
        self._drain_on_stop = drain
        self._stop.set()

    def join(self, timeout: float | None = None) -> bool:
        timed_out = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)
            timed_out = self._thread.is_alive()
        if not self._drain_on_stop:
            while True:
                try:
                    self.queue.get_nowait()
                except Empty:
                    break
        with self._pending_lock:
            self._pending_by_room.clear()
        return not timed_out

    def _run(self) -> None:
        conn = self.store.connect()
        try:
            while not self._stop.is_set() or (self._drain_on_stop and not self.queue.empty()):
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
            self._untrack_pending(job)
            self.stats.incr("db_write_successes")
            log_event(
                self._logger,
                DB_JOB_SUCCESS,
                level=logging.DEBUG,
                job_id=job.job_id,
                job_type=job.job_type,
            )
            if self._on_job_success is not None:
                self._on_job_success(job)
        except TRANSIENT_DB_ERRORS as exc:
            conn.rollback()
            job.attempts += 1
            job.last_error = str(exc)
            # Re-queue for retry via _put (not enqueue) so a retry is not counted
            # as a brand-new enqueue.
            if job.attempts < MAX_ATTEMPTS and self._put(job, track=False):
                return
            self._untrack_pending(job)
            self._record_failure(job)
        except Exception as exc:  # noqa: BLE001 - permanent failure, never retry
            conn.rollback()
            job.attempts += 1
            job.last_error = str(exc)
            self._untrack_pending(job)
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
        if self._on_job_failure is not None:
            self._on_job_failure(job)

    def _apply_job(self, conn: sqlite3.Connection, job: DbJob) -> None:
        payload = job.payload
        if job.job_type == "store_message":
            self.store.store_message(conn, payload["message"])
            return
        if job.job_type == "persist_system_message":
            self.store.persist_system_message(
                conn,
                payload["message"],
                event_details=payload.get(
                    "event_details",
                    {"body": payload["message"].get("body"), "message_id": payload["message"].get("message_id")},
                ),
            )
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
        if job.job_type == "prune_events":
            self.store.prune_events(conn, payload["keep_count"])
            return
        raise ValueError(f"unknown DB job type: {job.job_type}")
