from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic
from typing import Any

from chatserver.observability.logging import get_logger, log_event


@dataclass(slots=True)
class ScheduledJob:
    name: str
    interval: float
    callback: Callable[[], Any]
    next_run: float


class PeriodicScheduler:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        tick_seconds: float = 0.5,
        on_tick: Callable[[], None] | None = None,
    ) -> None:
        self.clock = clock
        self.tick_seconds = tick_seconds
        self.on_tick = on_tick
        self._jobs: list[ScheduledJob] = []
        self._stop = Event()
        self._thread: Thread | None = None
        self._logger = get_logger("chatserver.scheduler")

    def add_job(self, name: str, interval: float, callback: Callable[[], Any]) -> None:
        self._jobs.append(ScheduledJob(name, interval, callback, self.clock() + interval))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="chatserver-scheduler", daemon=False)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def run_pending(self) -> None:
        now = self.clock()
        for job in self._jobs:
            if now >= job.next_run:
                self._run_job(job)
                job.next_run = now + job.interval
        if self.on_tick:
            try:
                self.on_tick()
            except Exception as exc:  # noqa: BLE001 - a tick hook must never kill the loop
                log_event(self._logger, "scheduler_tick_error", error=str(exc))

    def _run_job(self, job: ScheduledJob) -> None:
        # One misbehaving job must never take down the scheduler thread, which
        # also drives heartbeats, idle eviction, pruning, and cache cleanup.
        try:
            job.callback()
        except Exception as exc:  # noqa: BLE001 - isolate per-job failures
            log_event(self._logger, "scheduler_job_error", job=job.name, error=str(exc))

    def _run(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            self.run_pending()
