""" Test polish round 2 """

from __future__ import annotations

import io
import socket
import time

import pytest

from chatserver.network.client import ChatClient
from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.protocol.messages import new_message_id, utc_timestamp
from chatserver.queues.db_jobs import DbJob
from chatserver.scheduling.scheduler import PeriodicScheduler
from conftest import connect_raw, read_until, running_server, send_frame


def test_handshake_server_busy_rejects_hello_when_queue_full(tmp_path, monkeypatch) -> None:
    with running_server(tmp_path) as server:
        real_enqueue = server.enqueue_db

        def busy_on_upsert(job: DbJob) -> bool:
            if job.job_type == "upsert_user":
                return False
            return real_enqueue(job)

        monkeypatch.setattr(server, "enqueue_db", busy_on_upsert)
        sock = socket.create_connection(server.address, timeout=2.0)
        sock.settimeout(2.0)
        try:
            send_frame(sock, {"type": "hello", "nick": "alice"})
            error = read_until(sock, "error")
            assert error["code"] == "server_busy"
            assert error.get("recoverable") is False
        finally:
            sock.close()


def test_client_connect_surfaces_handshake_server_busy(tmp_path, monkeypatch) -> None:
    with running_server(tmp_path) as server:
        real_enqueue = server.enqueue_db

        def busy_on_upsert(job: DbJob) -> bool:
            if job.job_type == "upsert_user":
                return False
            return real_enqueue(job)

        monkeypatch.setattr(server, "enqueue_db", busy_on_upsert)
        host, port = server.address
        client = ChatClient(host=host, port=port, nick="alice", output=io.StringIO())
        with pytest.raises(RuntimeError, match="server_busy"):
            client.connect()
        client.close()


def test_join_rolls_back_membership_when_audit_queue_full(tmp_path) -> None:
    with running_server(tmp_path, db_queue_size=2) as server:
        alice = connect_raw(server, "alice")
        session = server.nicks["alice"]
        server.db_writer.enqueue(DbJob("create_room", {"room": "fill1"}, priority=1))
        server.db_writer.enqueue(DbJob("create_room", {"room": "fill2"}, priority=1))
        send_frame(alice, {"type": "join", "room": "general"})
        error = read_until(alice, "error")
        assert error["code"] == "server_busy"
        assert "general" not in session.rooms
        assert server.rooms.counts().get("general", 0) == 0


def test_prune_e2e_forces_history_reload_from_db(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    try:
        store.create_room(conn, "general")
        for i in range(5):
            store.store_message(
                conn,
                {
                    "message_id": new_message_id(),
                    "kind": "chat",
                    "room": "general",
                    "sender": "alice",
                    "body": f"m{i}",
                    "server_timestamp": utc_timestamp(),
                },
            )
        conn.commit()
    finally:
        conn.close()

    with running_server(
        tmp_path,
        history_retention_count=50,
        room_cache_messages=50,
        history_limit=50,
    ) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")
        for i in range(5):
            send_frame(alice, {"type": "chat", "room": "general", "body": f"live{i}"})
            read_until(alice, "chat")
        assert server.history_cache.get("general") is not None
        assert server.db_writer.enqueue(
            DbJob("prune_history", {"keep_count": 2}, priority=5)
        )
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and server.history_cache.get("general") is not None:
            time.sleep(0.05)
        assert server.history_cache.get("general") is None
        send_frame(alice, {"type": "history", "room": "general", "limit": 10})
        history = read_until(alice, "history")
        assert len(history["messages"]) <= 2


def test_scheduler_join_reports_timeout_while_running() -> None:
    scheduler = PeriodicScheduler(tick_seconds=1000.0)
    scheduler.start()
    try:
        assert scheduler.join(0.001) is False
    finally:
        scheduler.stop()
        assert scheduler.join(2.0) is True
