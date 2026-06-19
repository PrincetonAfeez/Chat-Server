from __future__ import annotations

from chatserver.observability.stats import ServerStats
from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.persistence.writer import DbWriter
from chatserver.protocol.messages import new_message_id, utc_timestamp
from chatserver.queues.db_jobs import DbJob


def test_db_writer_serializes_message_writes(tmp_path) -> None:
    stats = ServerStats()
    store = SQLiteStore(tmp_path / "chat.db")
    writer = DbWriter(store, maxsize=10, stats=stats)
    writer.start()
    writer.enqueue(DbJob("create_room", {"room": "general"}))
    writer.enqueue(
        DbJob(
            "store_message",
            {
                "message": {
                    "type": "chat",
                    "kind": "chat",
                    "message_id": new_message_id(),
                    "room": "general",
                    "sender": "alice",
                    "body": "persist me",
                    "server_timestamp": utc_timestamp(),
                }
            },
        )
    )
    writer.stop(drain=True)
    writer.join(2.0)

    messages = store.recent_room_messages("general", 10)
    assert [message["body"] for message in messages] == ["persist me"]
    assert stats.snapshot()["db_write_successes"] == 2


def test_db_writer_queue_backpressure(tmp_path) -> None:
    stats = ServerStats()
    store = SQLiteStore(tmp_path / "chat.db")
    writer = DbWriter(store, maxsize=1, stats=stats)
    assert writer.enqueue(DbJob("create_room", {"room": "one"}))
    assert not writer.enqueue(DbJob("create_room", {"room": "two"}))
    assert stats.snapshot()["db_jobs_dropped"] == 1
