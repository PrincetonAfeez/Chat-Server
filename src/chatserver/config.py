""" Config module for the chat server library """

from __future__ import annotations

import json
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from chatserver.queues.backpressure import BackpressurePolicy

OUTBOUND_BACKPRESSURE_POLICIES = {
    BackpressurePolicy.DISCONNECT.value,
    BackpressurePolicy.DROP_OLDEST.value,
    BackpressurePolicy.DROP_NEWEST.value,
}
DB_BACKPRESSURE_POLICIES = {
    BackpressurePolicy.REJECT_CHAT.value,
    BackpressurePolicy.DISCONNECT.value,
}
KNOWN_ENGINES = {"threaded"}
KNOWN_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

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
_INT_FIELDS = _POSITIVE_INTS + ("port", "admin_port")
_FLOAT_FIELDS = _POSITIVE_FLOATS + _NON_NEGATIVE_FLOATS
_BOOL_FIELDS = ("admin_enabled",)


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 9000
    db_path: str = "chat.db"
    engine: str = "threaded"
    max_connections: int = 100
    max_message_size: int = 4096
    outbound_queue_size: int = 100
    outbound_backpressure_policy: str = BackpressurePolicy.DISCONNECT.value
    db_queue_size: int = 1000
    db_backpressure_policy: str = BackpressurePolicy.REJECT_CHAT.value
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
        if self.log_level.upper() not in KNOWN_LOG_LEVELS:
            allowed = ", ".join(sorted(KNOWN_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {allowed} (got {self.log_level!r})")
        self.log_level = self.log_level.upper()
        for name in _POSITIVE_INTS:
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1 (got {getattr(self, name)})")
        for name in _POSITIVE_FLOATS:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0 (got {getattr(self, name)})")
        for name in _NON_NEGATIVE_FLOATS:
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0 (got {getattr(self, name)})")
        if self.port < 0 or self.port > 65535:
            raise ValueError(f"port must be between 0 and 65535 (got {self.port})")
        if self.admin_port < 0 or self.admin_port > 65535:
            raise ValueError(f"admin_port must be between 0 and 65535 (got {self.admin_port})")
        if self.admin_enabled and self.admin_host not in {"127.0.0.1", "localhost"}:
            raise ValueError(
                f"admin_host must be a loopback address when admin is enabled (got {self.admin_host!r})"
            )
        if self.history_limit > self.room_cache_messages:
            raise ValueError(
                f"history_limit must be <= room_cache_messages "
                f"(got history_limit={self.history_limit}, room_cache_messages={self.room_cache_messages})"
            )
        if self.history_retention_count < self.room_cache_messages:
            raise ValueError(
                f"history_retention_count must be >= room_cache_messages "
                f"(got {self.history_retention_count}, room_cache_messages={self.room_cache_messages})"
            )

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
        coerced = cls._coerce_mapping(data)
        return cls(**coerced)

    @classmethod
    def _coerce_mapping(cls, data: dict[str, Any]) -> dict[str, Any]:
        coerced: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in data:
                continue
            value = data[field.name]
            if field.name in _INT_FIELDS:
                if isinstance(value, bool) or not isinstance(value, (int, str)):
                    raise ValueError(f"{field.name} must be an integer (got {type(value).__name__})")
                coerced[field.name] = int(value)
            elif field.name in _FLOAT_FIELDS:
                if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                    raise ValueError(f"{field.name} must be a number (got {type(value).__name__})")
                coerced[field.name] = float(value)
            elif field.name in _BOOL_FIELDS:
                if isinstance(value, bool):
                    coerced[field.name] = value
                elif isinstance(value, str):
                    lowered = value.lower()
                    if lowered in {"1", "true", "yes", "on"}:
                        coerced[field.name] = True
                    elif lowered in {"0", "false", "no", "off"}:
                        coerced[field.name] = False
                    else:
                        raise ValueError(f"{field.name} must be a boolean (got {value!r})")
                else:
                    raise ValueError(f"{field.name} must be a boolean (got {type(value).__name__})")
            elif field.name in {"host", "db_path", "engine", "log_level", "admin_host", "outbound_backpressure_policy", "db_backpressure_policy"}:
                if not isinstance(value, str):
                    raise ValueError(f"{field.name} must be a string (got {type(value).__name__})")
                coerced[field.name] = value
            else:
                coerced[field.name] = value
        return coerced

    def merged(self, overrides: dict[str, Any]) -> ServerConfig:
        data = asdict(self)
        for key, value in overrides.items():
            if value is not None:
                data[key] = value
        return ServerConfig.from_mapping(data)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
