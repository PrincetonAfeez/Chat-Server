from __future__ import annotations

from chatserver.scheduling.clock import ManualClock
from chatserver.security.rate_limit import RateLimiter


def test_rate_limiter_uses_injected_clock() -> None:
    clock = ManualClock()
    limiter = RateLimiter(2, 10.0, clock=clock)
    assert limiter.allow()
    assert limiter.allow()
    assert not limiter.allow()
    clock.advance(10.1)
    assert limiter.allow()
