from __future__ import annotations

import pytest

from chatserver.protocol.errors import ErrorCode, ProtocolError
from chatserver.protocol.validation import validate_client_message


def test_rejects_pre_handshake_chat() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_client_message('{"type":"chat","room":"general","body":"hi"}', handshaken=False)
    assert exc.value.code == ErrorCode.UNAUTHORIZED


def test_rejects_bad_room_name() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_client_message('{"type":"join","room":"bad room"}', handshaken=True)
    assert exc.value.code == ErrorCode.INVALID_ROOM


def test_accepts_hello() -> None:
    assert validate_client_message('{"type":"hello","nick":"princeton"}', handshaken=False) == {
        "type": "hello",
        "nick": "princeton",
    }


def test_unknown_message_type_is_stable_error() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_client_message('{"type":"dance"}', handshaken=True)
    assert exc.value.code == ErrorCode.UNKNOWN_COMMAND
