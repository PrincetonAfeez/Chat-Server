from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class DbJob:
    job_type: str
    payload: dict[str, Any]
    priority: int = 5
    job_id: str = field(default_factory=lambda: f"job_{uuid4().hex[:16]}")
    created_at: float = field(default_factory=time)
    attempts: int = 0
    last_error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "created_at": self.created_at,
            "attempts": self.attempts,
            "priority": self.priority,
            "last_error": self.last_error,
            "payload_keys": sorted(self.payload.keys()),
        }
