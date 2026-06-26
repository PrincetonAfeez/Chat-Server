"""Server-to-client frame builders and id/timestamp helpers 

These builders are the single source of truth for the shape of every frame the
server sends. The ``*Frame`` TypedDicts document the wire contract (see
PROTOCOL.md); the builders return plain dicts so frames flow unchanged through
the cache, outbound queues, and the JSON Lines encoder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict
from uuid import uuid4

Frame = dict[str, Any]


class WelcomeFrame(TypedDict):
    type: str
    user_id: str
    nick: str


class ChatFrame(TypedDict):
    type: str
    kind: str
    message_id: str
    room: str
    sender: str
    body: str
    server_timestamp: str
    metadata: dict[str, Any]


class DmFrame(TypedDict):
    type: str
    kind: str
    message_id: str
    sender: str
    to: str
    recipient: str
    body: str
    server_timestamp: str
    metadata: dict[str, Any]


def utc_timestamp() -> str:
    """Return the current UTC time as an ISO-8601 string ending in ``Z``."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_message_id() -> str:
    """Return a fresh ``m_…`` server-assigned message id."""
    return f"m_{uuid4().hex[:16]}"


def welcome_frame(*, user_id: str, nick: str) -> Frame:
    return {"type": "welcome", "user_id": user_id, "nick": nick}


def chat_frame(*, message_id: str, room: str, sender: str, body: str, session_id: str) -> Frame:
    return {
        "type": "chat",
        "kind": "chat",
        "message_id": message_id,
        "room": room,
        "sender": sender,
        "body": body,
        "server_timestamp": utc_timestamp(),
        "metadata": {"session_id": session_id},
    }


def dm_frame(*, message_id: str, sender: str, to: str, body: str, session_id: str) -> Frame:
    return {
        "type": "dm",
        "kind": "dm",
        "message_id": message_id,
        "sender": sender,
        "to": to,
        "recipient": to,
        "body": body,
        "server_timestamp": utc_timestamp(),
        "metadata": {"session_id": session_id},
    }


def system_message(body: str, *, room: str | None = None) -> Frame:
    """A bare system notice (no message_id); used for transient broadcasts."""
    message: Frame = {
        "type": "system",
        "body": body,
        "server_timestamp": utc_timestamp(),
    }
    if room is not None:
        message["room"] = room
    return message


def room_system_message(*, room: str, body: str, message_id: str) -> Frame:
    """A persisted room system notice (X joined/left/renamed) with an id."""
    message = system_message(body, room=room)
    message.update(
        {
            "kind": "system",
            "message_id": message_id,
            "sender": "system",
            "metadata": {"event": "system"},
        }
    )
    return message


def history_frame(*, room: str, messages: list[Frame]) -> Frame:
    return {"type": "history", "room": room, "messages": messages}


def who_frame(*, users: list[str], room: str | None = None) -> Frame:
    frame: Frame = {"type": "who", "users": users}
    if room is not None:
        frame["room"] = room
    return frame


def rooms_frame(*, rooms: list[dict[str, Any]]) -> Frame:
    return {"type": "rooms", "rooms": rooms}


def ping_frame(*, nonce: str) -> Frame:
    return {"type": "ping", "nonce": nonce}
