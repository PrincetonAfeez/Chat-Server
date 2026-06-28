""" Test cache scheduler concurrency """

from __future__ import annotations

from threading import Thread

from chatserver.cache.history_cache import HistoryCache
from chatserver.scheduling.clock import ManualClock
from chatserver.scheduling.scheduler import PeriodicScheduler


def test_history_cache_is_safe_under_concurrent_access() -> None:
    # Before the lock was added, concurrent append/get + cleanup_expired raised
    # "OrderedDict mutated during iteration". This must now run cleanly.
    cache = HistoryCache(max_rooms=32, messages_per_room=20, ttl_seconds=0.0)
    errors: list[str] = []

    def writer(worker: int) -> None:
        try:
            for i in range(4000):
                room = f"room{(worker + i) % 24}"
                cache.append(room, {"body": f"m{i}"})
                cache.get(room)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    def cleaner() -> None:
        try:
            for _ in range(4000):
                cache.cleanup_expired()
                cache.snapshot()
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [Thread(target=writer, args=(w,)) for w in range(4)] + [Thread(target=cleaner) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []


def test_scheduler_survives_a_failing_job() -> None:
    clock = ManualClock()
    scheduler = PeriodicScheduler(clock=clock, tick_seconds=0.01)
    counters = {"boom": 0, "ok": 0}

    def boom() -> None:
        counters["boom"] += 1
        raise ValueError("intentional job failure")

    def ok() -> None:
        counters["ok"] += 1

    scheduler.add_job("boom", 1.0, boom)
    scheduler.add_job("ok", 1.0, ok)

    # Two due ticks: a raising job must not prevent the sibling job from running,
    # and run_pending itself must never propagate the exception.
    for _ in range(2):
        clock.advance(1.0)
        scheduler.run_pending()

    assert counters["boom"] == 2
    assert counters["ok"] == 2
