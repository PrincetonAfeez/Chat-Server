from __future__ import annotations

import re
from typing import Any

from .errors import ErrorCode, ProtocolError
from .framing import decode_json_frame

CLIENT_MESSAGE_TYPES = {
    "hello",
    "chat",
    "join",
    "leave",
    "dm",
    "history",
    "who",
    "rooms",
    "pong",
}

ROOM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
NICK_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,31}$")
# C0 controls (incl. ESC/newline/tab), DEL, and C1 controls. Blocking these
# keeps a hostile body from carrying terminal escape sequences that would
# hijack another user's terminal when their client prints the message.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
MAX_BODY_CHARS = 2000


def validate_client_message(frame: str, *, handshaken: bool) -> dict[str, Any]:
    message = decode_json_frame(frame)
    msg_type = _require_str(message, "type")
    if msg_type not in CLIENT_MESSAGE_TYPES:
        raise ProtocolError(ErrorCode.UNKNOWN_COMMAND, f"Unknown message type: {msg_type}")

    if not handshaken and msg_type != "hello":
        raise ProtocolError(
            ErrorCode.UNAUTHORIZED,
            "Client must complete hello/welcome handshake first",
            recoverable=True,
        )

    if msg_type == "hello":
        nick = validate_nick(_require_str(message, "nick"))
        return {"type": "hello", "nick": nick}
    if msg_type == "join":
        return {"type": "join", "room": validate_room(_require_str(message, "room"))}
    if msg_type == "leave":
        return {"type": "leave", "room": validate_room(_require_str(message, "room"))}
    if msg_type == "chat":
        return {
            "type": "chat",
            "room": validate_room(_require_str(message, "room")),
            "body": validate_body(_require_str(message, "body")),
        }
    if msg_type == "dm":
        return {
            "type": "dm",
            "to": validate_nick(_require_str(message, "to")),
            "body": validate_body(_require_str(message, "body")),
        }
    if msg_type == "history":
        room_value = message.get("room", "general")
        if not isinstance(room_value, str):
            raise ProtocolError(ErrorCode.INVALID_ROOM, "room must be a string")
        limit = message.get("limit", 25)
        if not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ProtocolError(ErrorCode.INVALID_MESSAGE, "limit must be an integer from 1 to 200")
        return {"type": "history", "room": validate_room(room_value), "limit": limit}
    if msg_type == "who":
        room = message.get("room")
        if room is not None and not isinstance(room, str):
            raise ProtocolError(ErrorCode.INVALID_ROOM, "room must be a string")
        return {"type": "who", "room": validate_room(room) if room else None}
    if msg_type == "rooms":
        return {"type": "rooms"}
    if msg_type == "pong":
        nonce = message.get("nonce", "")
        if not isinstance(nonce, str):
            raise ProtocolError(ErrorCode.INVALID_MESSAGE, "nonce must be a string")
        return {"type": "pong", "nonce": nonce}

    raise ProtocolError(ErrorCode.UNKNOWN_COMMAND, f"Unhandled message type: {msg_type}")


def validate_room(room: str) -> str:
    if not ROOM_RE.match(room):
        raise ProtocolError(
            ErrorCode.INVALID_ROOM,
            "Room names must be 1-32 chars: letters, numbers, underscore, or dash",
        )
    return room


def validate_nick(nick: str) -> str:
    if not NICK_RE.match(nick):
        raise ProtocolError(
            ErrorCode.INVALID_NICK,
            "Nicknames must be 2-32 chars, start with a letter, and use letters, numbers, underscore, or dash",
        )
    return nick


def validate_body(body: str) -> str:
    if not body or len(body) > MAX_BODY_CHARS:
        raise ProtocolError(
            ErrorCode.INVALID_MESSAGE,
            f"body must be 1-{MAX_BODY_CHARS} characters",
        )
    if CONTROL_RE.search(body):
        raise ProtocolError(
            ErrorCode.INVALID_MESSAGE,
            "body must not contain control characters",
        )
    return body


def _require_str(message: dict[str, Any], key: str) -> str:
    value = message.get(key)
    if not isinstance(value, str):
        raise ProtocolError(ErrorCode.INVALID_MESSAGE, f"{key} is required and must be a string")
    return value
