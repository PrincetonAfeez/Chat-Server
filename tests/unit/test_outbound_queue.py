from __future__ import annotations

from chatserver.queues.outbound import OutboundQueue


def test_put_nowait_reports_overflow() -> None:
    queue = OutboundQueue(maxsize=1)
    assert queue.put_nowait({"n": 1})
    assert not queue.put_nowait({"n": 2})


def test_put_drop_oldest_evicts_oldest_to_make_room() -> None:
    queue = OutboundQueue(maxsize=2)
    assert queue.put_nowait({"n": 1})
    assert queue.put_nowait({"n": 2})
    # Full now: drop_oldest discards {n:1} and enqueues {n:3}.
    assert queue.put_drop_oldest({"n": 3})
    assert queue.get(timeout=1) == {"n": 2}
    assert queue.get(timeout=1) == {"n": 3}
    assert queue.empty()
