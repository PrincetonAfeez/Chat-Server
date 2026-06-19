from __future__ import annotations

import json
from typing import Any

from .errors import ErrorCode, ProtocolError


class FrameDecoder:
    """Incrementally decodes JSON Lines frames from a TCP byte stream."""

    def __init__(self, max_frame_size: int) -> None:
        self.max_frame_size = max_frame_size
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> tuple[list[str], list[ProtocolError]]:
        frames: list[str] = []
        errors: list[ProtocolError] = []
        if not data:
            return frames, errors

        self._buffer.extend(data)
        while True:
            newline_index = self._find_newline()
            if newline_index < 0:
                if len(self._buffer) > self.max_frame_size:
                    self._buffer.clear()
                    errors.append(
                        ProtocolError(
                            ErrorCode.FRAME_TOO_LARGE,
                            "Frame exceeded max_message_size before newline",
                            recoverable=False,
                        )
                    )
                break

            raw = bytes(self._buffer[:newline_index])
            del self._buffer[: newline_index + 1]
            if len(raw) > self.max_frame_size:
                errors.append(
                    ProtocolError(
                        ErrorCode.FRAME_TOO_LARGE,
                        "Frame exceeded max_message_size",
                        recoverable=False,
                    )
                )
                continue
            if raw.endswith(b"\r"):
                raw = raw[:-1]
            try:
                frames.append(raw.decode("utf-8"))
            except UnicodeDecodeError as exc:
                errors.append(
                    ProtocolError(
                        ErrorCode.BAD_JSON,
                        "Frame is not valid UTF-8",
                        recoverable=True,
                        details={"reason": str(exc)},
                    )
                )
        return frames, errors

    def _find_newline(self) -> int:
        try:
            return self._buffer.index(0x0A)
        except ValueError:
            return -1


def encode_frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    return payload.encode("utf-8") + b"\n"


def decode_json_frame(frame: str) -> dict[str, Any]:
    try:
        value = json.loads(frame)
    except json.JSONDecodeError as exc:
        raise ProtocolError(
            ErrorCode.BAD_JSON,
            "Malformed JSON frame",
            recoverable=True,
            details={"line": exc.lineno, "column": exc.colno},
        ) from exc
    if not isinstance(value, dict):
        raise ProtocolError(
            ErrorCode.INVALID_MESSAGE,
            "Frame must contain a JSON object",
            recoverable=True,
        )
    return value
