"""Demonstrates how a blocking broadcast lets one slow client stall the room."""

from __future__ import annotations

from queue import Full, Queue
from typing import Any

from chatserver.queues.outbound import OutboundQueue


def demonstrate() -> dict[str, Any]:
    capacity = 3
    total = 10

    # Naive model: broadcast writes directly to each recipient's socket. A slow
    # client (modeled as a full, never-drained kernel buffer) blocks the loop,
    # so the broadcast stalls and later recipients are starved.
    slow_sink: Queue[int] = Queue(maxsize=capacity)
    naive_stalled_at: int | None = None
    for i in range(total):
        try:
            slow_sink.put_nowait(i)  # a real blocking sendall would now hang here
        except Full:
            naive_stalled_at = i
            break

    # Safe model: each client owns a bounded queue. Overflow is detected and
    # returned to the caller (the server turns it into an eviction) instead of
    # blocking delivery to everyone else.
    safe_queue = OutboundQueue(maxsize=capacity)
    accepted = sum(1 for i in range(total) if safe_queue.put_nowait({"i": i}))

    return {
        "naive_broadcast_stalled_at_message": naive_stalled_at,
        "safe_queue_accepted": accepted,
        "safe_queue_overflow_signalled": accepted < total,
        "lesson": "give every client a bounded outbound queue; overflow evicts it, not the room.",
    }


def unsafe_example() -> str:
    result = demonstrate()
    return (
        "Unsafe slow-client demo: a direct blocking broadcast stalled at message "
        f"{result['naive_broadcast_stalled_at_message']} once the slow client's buffer filled. "
        f"A bounded per-client queue instead accepted {result['safe_queue_accepted']} and signalled "
        f"overflow for the rest. {result['lesson']}"
    )
