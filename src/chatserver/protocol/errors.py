from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    BAD_JSON = "bad_json"
    FRAME_TOO_LARGE = "frame_too_large"
    INVALID_MESSAGE = "invalid_message"
    INVALID_ROOM = "invalid_room"
    INVALID_NICK = "invalid_nick"
    NICK_TAKEN = "nick_taken"
    UNAUTHORIZED = "unauthorized"
    UNKNOWN_COMMAND = "unknown_command"
    ROOM_NOT_FOUND = "room_not_found"
    USER_NOT_FOUND = "user_not_found"
    RATE_LIMITED = "rate_limited"
    SLOW_CLIENT = "slow_client"
    SERVER_SHUTTING_DOWN = "server_shutting_down"
    SERVER_BUSY = "server_busy"
    SERVER_FULL = "server_full"


@dataclass(slots=True)
class ProtocolError(Exception):
    code: ErrorCode
    message: str
    recoverable: bool = True
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def error_frame(
    code: ErrorCode | str,
    message: str,
    *,
    recoverable: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frame: dict[str, Any] = {
        "type": "error",
        "code": str(code),
        "message": message,
        "recoverable": recoverable,
    }
    if details:
        frame["details"] = details
    return frame
