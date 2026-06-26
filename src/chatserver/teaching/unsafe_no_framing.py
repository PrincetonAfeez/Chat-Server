"""Demonstrates why 'one recv() == one message' is wrong on a TCP stream """

from __future__ import annotations

import json
from typing import Any

from chatserver.protocol.framing import FrameDecoder


def _naive_parse(chunks: list[bytes]) -> list[dict[str, Any]]:
    # The bug: assume every recv() returns exactly one whole JSON message.
    return [json.loads(chunk.decode("utf-8")) for chunk in chunks]


def demonstrate() -> dict[str, Any]:
    # One logical frame split across two reads, then two frames merged into one.
    chunks = [b'{"type":"hel', b'lo","nick":"ada"}\n{"type":"rooms"}\n']
    try:
        _naive_parse(chunks)
        naive_error: str | None = None
    except Exception as exc:  # noqa: BLE001 - capturing the failure is the point
        naive_error = f"{type(exc).__name__}: {exc}"

    decoder = FrameDecoder(4096)
    safe_frames: list[str] = []
    for chunk in chunks:
        frames, _errors = decoder.feed(chunk)
        safe_frames.extend(frames)

    return {
        "naive_error": naive_error,
        "safe_frames": safe_frames,
        "lesson": "TCP is a byte stream; frame on newlines and buffer partial reads.",
    }


def unsafe_example() -> str:
    result = demonstrate()
    return (
        "Unsafe framing demo: a naive one-recv()-per-message parser failed with "
        f"[{result['naive_error']}], while FrameDecoder recovered "
        f"{len(result['safe_frames'])} frames {result['safe_frames']}. {result['lesson']}"
    )
