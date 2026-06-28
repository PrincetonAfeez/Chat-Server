"""Property-based fuzzing of the frame decoder — the most security-critical
parser, since it turns hostile bytes into structure """

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from chatserver.protocol.framing import FrameDecoder

_json_scalar = st.none() | st.booleans() | st.integers(-1000, 1000) | st.text(max_size=20)
_json_object = st.dictionaries(st.text(min_size=1, max_size=8), _json_scalar, max_size=5)


@settings(max_examples=300)
@given(
    messages=st.lists(_json_object, max_size=15),
    chunk_sizes=st.lists(st.integers(min_value=1, max_value=40), min_size=1, max_size=10),
)
def test_decoder_recovers_frames_across_arbitrary_byte_splits(
    messages: list[dict[str, object]],
    chunk_sizes: list[int],
) -> None:
    # json.dumps(ensure_ascii=True) escapes every control char, so the only
    # newline in the stream is our frame delimiter.
    frames = [json.dumps(m, separators=(",", ":")) for m in messages]
    stream = "".join(f + "\n" for f in frames).encode("utf-8")

    decoder = FrameDecoder(1 << 20)
    recovered: list[str] = []
    errors = []
    offset = 0
    cursor = 0
    while offset < len(stream):
        size = chunk_sizes[cursor % len(chunk_sizes)]
        got, errs = decoder.feed(stream[offset : offset + size])
        recovered.extend(got)
        errors.extend(errs)
        offset += size
        cursor += 1

    assert errors == []
    assert recovered == frames
    assert decoder.buffered_bytes == 0
