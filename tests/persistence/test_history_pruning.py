from __future__ import annotations

from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.protocol.messages import new_message_id, utc_timestamp


def _chat(room: str, body: str) -> dict:
    return {
        "type": "chat",
        "kind": "chat",
        "message_id": new_message_id(),
        "room": room,
        "sender": "alice",
        "body": body,
        "server_timestamp": utc_timestamp(),
    }


def test_prune_history_keeps_recent_messages_for_every_room(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    try:
        for i in range(10):
            store.store_message(conn, _chat("general", f"g{i}"))
        for i in range(10):
            store.store_message(conn, _chat("random", f"r{i}"))
        conn.commit()
        # room=None prunes *every* room in one pass, including idle ones.
        store.prune_history(conn, 3, room=None)
        conn.commit()
    finally:
        conn.close()

    general = [m["body"] for m in store.recent_room_messages("general", 100)]
    random_room = [m["body"] for m in store.recent_room_messages("random", 100)]
    assert general == ["g7", "g8", "g9"]
    assert random_room == ["r7", "r8", "r9"]


def test_prune_history_single_room(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    try:
        for i in range(6):
            store.store_message(conn, _chat("general", f"g{i}"))
            store.store_message(conn, _chat("random", f"r{i}"))
        conn.commit()
        store.prune_history(conn, 2, room="general")
        conn.commit()
    finally:
        conn.close()

    assert [m["body"] for m in store.recent_room_messages("general", 100)] == ["g4", "g5"]
    # The targeted prune must not touch the other room.
    assert len(store.recent_room_messages("random", 100)) == 6
