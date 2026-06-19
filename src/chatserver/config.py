from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

OUTBOUND_BACKPRESSURE_POLICIES = {"disconnect", "drop_oldest", "drop_newest"}
DB_BACKPRESSURE_POLICIES = {"reject_chat", "disconnect"}
KNOWN_ENGINES = {"threaded", "selectors", "asyncio"}

# Fields that must be >= 1 (a value of 0 would silently make a bounded Queue
# unbounded, disabling backpressure, or reject every client/message).
_POSITIVE_INTS = (
    "max_connections",
    "max_message_size",
    "outbound_queue_size",
    "db_queue_size",
    "history_limit",
    "history_retention_count",
    "event_retention_count",
    "room_cache_messages",
    "max_cached_rooms",
    "rate_limit_messages",
)
# Durations that must be strictly positive.
_POSITIVE_FLOATS = (
    "heartbeat_interval",
    "idle_timeout",
    "handshake_timeout",
    "rate_limit_window",
    "shutdown_timeout",
)
# Durations where 0 is a valid "disabled" sentinel.
_NON_NEGATIVE_FLOATS = ("cache_ttl", "stats_interval")


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 9000
    db_path: str = "chat.db"
    engine: str = "threaded"
    max_connections: int = 100
    max_message_size: int = 4096
    outbound_queue_size: int = 100
    outbound_backpressure_policy: str = "disconnect"
    db_queue_size: int = 1000
    db_backpressure_policy: str = "reject_chat"
    heartbeat_interval: float = 20.0
    idle_timeout: float = 60.0
    handshake_timeout: float = 10.0
    history_limit: int = 50
    history_retention_count: int = 1000
    event_retention_count: int = 10000
    room_cache_messages: int = 50
    max_cached_rooms: int = 128
    cache_ttl: float = 600.0
    rate_limit_messages: int = 20
    rate_limit_window: float = 5.0
    stats_interval: float = 30.0
    log_level: str = "INFO"
    shutdown_timeout: float = 5.0
    admin_enabled: bool = False
    admin_host: str = "127.0.0.1"
    admin_port: int = 0

    def __post_init__(self) -> None:
        if self.outbound_backpressure_policy not in OUTBOUND_BACKPRESSURE_POLICIES:
            allowed = ", ".join(sorted(OUTBOUND_BACKPRESSURE_POLICIES))
            raise ValueError(
                f"outbound_backpressure_policy must be one of: {allowed} (got {self.outbound_backpressure_policy!r})"
            )
        if self.db_backpressure_policy not in DB_BACKPRESSURE_POLICIES:
            allowed = ", ".join(sorted(DB_BACKPRESSURE_POLICIES))
            raise ValueError(f"db_backpressure_policy must be one of: {allowed} (got {self.db_backpressure_policy!r})")
        if self.engine not in KNOWN_ENGINES:
            allowed = ", ".join(sorted(KNOWN_ENGINES))
            raise ValueError(f"engine must be one of: {allowed} (got {self.engine!r})")
        for name in _POSITIVE_INTS:
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1 (got {getattr(self, name)})")
        for name in _POSITIVE_FLOATS:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0 (got {getattr(self, name)})")
        for name in _NON_NEGATIVE_FLOATS:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0 (got {getattr(self, name)})")
        if self.port < 0 or self.admin_port < 0:
            raise ValueError("port and admin_port must be >= 0")

    @classmethod
    def from_file(cls, path: str | Path) -> ServerConfig:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        raw = path.read_bytes()
        if path.suffix.lower() == ".json":
            data = json.loads(raw.decode("utf-8"))
        else:
            data = tomllib.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("configuration file must contain an object")
        if "server" in data and isinstance(data["server"], dict):
            data = data["server"]
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> ServerConfig:
        allowed = {field.name for field in fields(cls)}
        unknown = set(data) - allowed
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unknown config keys: {names}")
        return cls(**data)

    def merged(self, overrides: dict[str, Any]) -> ServerConfig:
        data = asdict(self)
        for key, value in overrides.items():
            if value is not None:
                data[key] = value
        return ServerConfig.from_mapping(data)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
