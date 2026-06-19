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


def test_rejects_control_characters_in_body() -> None:
    #  is ESC — an ANSI terminal-escape lead-in that must not pass through.
    with pytest.raises(ProtocolError) as exc:
        validate_client_message(
            '{"type":"chat","room":"general","body":"hi\\u001b[2Jthere"}',
            handshaken=True,
        )
    assert exc.value.code == ErrorCode.INVALID_MESSAGE


def test_rejects_newline_in_body() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_client_message('{"type":"chat","room":"general","body":"a\\nb"}', handshaken=True)
    assert exc.value.code == ErrorCode.INVALID_MESSAGE


def test_accepts_normal_unicode_body() -> None:
    msg = validate_client_message('{"type":"chat","room":"general","body":"héllo 🌍"}', handshaken=True)
    assert msg["body"] == "héllo 🌍"
