from __future__ import annotations

import pytest

from chatserver.config import ServerConfig


def test_rejects_unknown_outbound_policy() -> None:
    with pytest.raises(ValueError, match="outbound_backpressure_policy"):
        ServerConfig(outbound_backpressure_policy="explode")


def test_rejects_unknown_db_policy() -> None:
    with pytest.raises(ValueError, match="db_backpressure_policy"):
        ServerConfig(db_backpressure_policy="explode")


def test_merged_overrides_validate_too() -> None:
    base = ServerConfig()
    merged = base.merged({"outbound_backpressure_policy": "drop_oldest"})
    assert merged.outbound_backpressure_policy == "drop_oldest"
    with pytest.raises(ValueError):
        base.merged({"db_backpressure_policy": "nope"})


def test_admin_disabled_by_default() -> None:
    assert ServerConfig().admin_enabled is False


def test_rejects_nonpositive_queue_sizes() -> None:
    # A maxsize of 0 would make queue.Queue unbounded and silently disable
    # backpressure — exactly what this project is about.
    with pytest.raises(ValueError, match="outbound_queue_size"):
        ServerConfig(outbound_queue_size=0)
    with pytest.raises(ValueError, match="db_queue_size"):
        ServerConfig(db_queue_size=0)


def test_rejects_nonpositive_limits_and_durations() -> None:
    with pytest.raises(ValueError, match="max_connections"):
        ServerConfig(max_connections=0)
    with pytest.raises(ValueError, match="rate_limit_messages"):
        ServerConfig(rate_limit_messages=0)
    with pytest.raises(ValueError, match="idle_timeout"):
        ServerConfig(idle_timeout=0)


def test_allows_disabled_sentinels() -> None:
    # 0 is a valid "disabled" value for these.
    cfg = ServerConfig(stats_interval=0.0, cache_ttl=0.0, port=0, admin_port=0)
    assert cfg.stats_interval == 0.0
    assert cfg.cache_ttl == 0.0


def test_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="engine"):
        ServerConfig(engine="quantum")
