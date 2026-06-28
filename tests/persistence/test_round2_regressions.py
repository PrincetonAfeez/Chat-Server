""" Test round 2 regressions """

from __future__ import annotations

import sqlite3

import pytest

from chatserver.observability.stats import ServerStats
from chatserver.persistence.migrations import SCHEMA_VERSION, init_db
from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.persistence.writer import DbWriter
from chatserver.protocol.messages import new_message_id, utc_timestamp
from chatserver.queues.db_jobs import DbJob


def _chat_message(*, body: str, room: str = "general", metadata: dict[str, str] | None = None) -> dict[str, object]:
    message: dict[str, object] = {
        "type": "chat",
        "kind": "chat",
        "message_id": new_message_id(),
        "room": room,
        "sender": "alice",
        "body": body,
        "server_timestamp": utc_timestamp(),
    }
    if metadata is not None:
        message["metadata"] = metadata
    return message


def test_store_message_rejects_missing_server_timestamp(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    try:
        with pytest.raises(ValueError, match="server_timestamp"):
            store.store_message(
                conn,
                {
                    "message_id": new_message_id(),
                    "body": "hi",
                    "room": "general",
                },
            )
    finally:
        conn.close()


def test_store_message_rejects_duplicate_message_id(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    message = _chat_message(body="once")
    try:
        store.create_room(conn, "general")
        store.store_message(conn, message)
        conn.commit()
        with pytest.raises(ValueError, match="duplicate message_id"):
            store.store_message(conn, message)
    finally:
        conn.close()


def test_metadata_round_trips_through_sqlite(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    try:
        store.create_room(conn, "general")
        store.store_message(conn, _chat_message(body="meta", metadata={"flag": "yes"}))
        conn.commit()
    finally:
        conn.close()
    stored = store.recent_room_messages("general", 5)[0]
    assert stored.get("metadata") == {"flag": "yes"}


def test_persist_system_message_writes_message_and_event(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    notice = {
        "type": "system",
        "kind": "system",
        "message_id": new_message_id(),
        "room": "general",
        "sender": "system",
        "body": "alice joined general",
        "server_timestamp": utc_timestamp(),
    }
    try:
        store.create_room(conn, "general")
        store.persist_system_message(conn, notice, event_details={"body": notice["body"]})
        conn.commit()
        messages = store.recent_room_messages("general", 5)
        events = conn.execute("SELECT COUNT(*) FROM events WHERE event_type = 'system'").fetchone()[0]
    finally:
        conn.close()
    assert messages[0]["body"] == "alice joined general"
    assert events == 1


def test_init_db_skips_when_user_version_current(tmp_path) -> None:
    db_path = tmp_path / "chat.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        version_before = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version_before == SCHEMA_VERSION
    finally:
        conn.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        version_after = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    assert version_after == SCHEMA_VERSION
    assert any(row[0] == "messages" for row in tables)


def test_store_message_rejects_missing_room_for_chat(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    try:
        with pytest.raises(ValueError, match="room"):
            store.store_message(
                conn,
                {
                    "message_id": new_message_id(),
                    "kind": "chat",
                    "body": "hi",
                    "server_timestamp": utc_timestamp(),
                },
            )
    finally:
        conn.close()


def test_db_writer_queue_orders_by_priority(tmp_path) -> None:
    stats = ServerStats()
    store = SQLiteStore(tmp_path / "chat.db")
    writer = DbWriter(store, maxsize=10, stats=stats)
    writer._put(DbJob("create_room", {"room": "low"}, priority=1), track=False)
    writer._put(
        DbJob("store_message", {"message": _chat_message(body="high")}, priority=5),
        track=False,
    )
    _, _, first = writer.queue.get_nowait()
    assert first.job_type == "store_message"
    assert first.priority == 5


def test_db_writer_stop_without_drain_discards_queue(tmp_path) -> None:
    stats = ServerStats()
    store = SQLiteStore(tmp_path / "chat.db")
    writer = DbWriter(store, maxsize=2, stats=stats)
    writer.start()
    writer.enqueue(DbJob("create_room", {"room": "one"}))
    writer.enqueue(DbJob("create_room", {"room": "two"}))
    writer.stop(drain=False)
    writer.join(timeout=1.0)
    assert writer.queue.empty()
    assert stats.snapshot()["db_write_successes"] == 0
