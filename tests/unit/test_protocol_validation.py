""" Test protocol validation """

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


def test_rejects_bool_history_limit() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_client_message('{"type":"history","room":"general","limit":true}', handshaken=True)
    assert exc.value.code == ErrorCode.INVALID_MESSAGE


def test_rejects_history_limit_out_of_range() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_client_message('{"type":"history","room":"general","limit":0}', handshaken=True)
    assert exc.value.code == ErrorCode.INVALID_MESSAGE
    with pytest.raises(ProtocolError) as exc:
        validate_client_message('{"type":"history","room":"general","limit":201}', handshaken=True)
    assert exc.value.code == ErrorCode.INVALID_MESSAGE


def test_rejects_invalid_nick_on_hello() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_client_message('{"type":"hello","nick":"1bad"}', handshaken=False)
    assert exc.value.code == ErrorCode.INVALID_NICK


def test_rejects_oversized_body_for_configured_frame_cap() -> None:
    with pytest.raises(ProtocolError) as exc:
        validate_client_message(
            '{"type":"chat","room":"general","body":"' + ("x" * 5000) + '"}',
            handshaken=True,
            max_message_size=4096,
        )
    assert exc.value.code == ErrorCode.INVALID_MESSAGE


def test_rejects_long_pong_nonce() -> None:
    nonce = "n" * 129
    with pytest.raises(ProtocolError) as exc:
        validate_client_message(f'{{"type":"pong","nonce":"{nonce}"}}', handshaken=True)
    assert exc.value.code == ErrorCode.INVALID_MESSAGE
