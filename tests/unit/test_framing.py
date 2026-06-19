from __future__ import annotations

import pytest

from chatserver.protocol.errors import ErrorCode, ProtocolError
from chatserver.protocol.framing import FrameDecoder, decode_json_frame, encode_frame


def test_partial_frame_buffers_until_newline() -> None:
    decoder = FrameDecoder(100)
    frames, errors = decoder.feed(b'{"type":"rooms"')
    assert frames == []
    assert errors == []

    frames, errors = decoder.feed(b"}\n")
    assert frames == ['{"type":"rooms"}']
    assert errors == []


def test_merged_frames_decode_separately() -> None:
    decoder = FrameDecoder(100)
    frames, errors = decoder.feed(b'{"type":"rooms"}\n{"type":"who"}\n')
    assert frames == ['{"type":"rooms"}', '{"type":"who"}']
    assert errors == []


def test_oversized_frame_is_rejected() -> None:
    decoder = FrameDecoder(5)
    frames, errors = decoder.feed(b'{"type":"rooms"}\n')
    assert frames == []
    assert errors[0].code == ErrorCode.FRAME_TOO_LARGE


def test_malformed_json_raises_protocol_error() -> None:
    with pytest.raises(ProtocolError) as exc:
        decode_json_frame("{nope")
    assert exc.value.code == ErrorCode.BAD_JSON


def test_encode_adds_newline() -> None:
    assert encode_frame({"type": "rooms"}).endswith(b"\n")
