""" Test round 4 regressions """

from __future__ import annotations

import json
import socket
import time

import pytest

from chatserver.config import ServerConfig
from chatserver.network.server import ChatServer
from chatserver.persistence import migrations
from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.protocol.framing import FrameDecoder, encode_frame
from chatserver.protocol.messages import chat_frame, new_message_id, utc_timestamp
from chatserver.queues.db_jobs import DbJob
from chatserver.scheduling.clock import ManualClock
from conftest import connect_raw, read_until, running_server, send_frame


def test_history_cache_hit_merges_pending_writes(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "join", "room": "general"})
        read_until(alice, "history")

        cached = chat_frame(
            message_id=new_message_id(),
            room="general",
            sender="alice",
            body="cached-only",
            session_id="s_test",
        )
        pending = chat_frame(
            message_id=new_message_id(),
            room="general",
            sender="alice",
            body="pending-write",
            session_id="s_test",
        )
        server.history_cache.warm("general", [cached])
        with server.db_writer._pending_lock:
            server.db_writer._pending_by_room["general"].append(pending)

        send_frame(alice, {"type": "history", "room": "general", "limit": 10})
        history = read_until(alice, "history")
        bodies = [item["body"] for item in history["messages"]]
        assert "cached-only" in bodies
        assert "pending-write" in bodies


def test_kick_emits_kicked_error_on_wire(tmp_path) -> None:
    with running_server(tmp_path, admin_enabled=True, admin_port=0) as server:
        alice = connect_raw(server, "alice")
        host, port = server.admin_address
        assert port is not None
        with socket.create_connection((host, port), timeout=2.0) as admin_sock:
            admin_sock.sendall(encode_frame({"command": "kick", "nick": "alice"}))
            decoder = FrameDecoder(1 << 20)
            admin_sock.settimeout(2.0)
            data = admin_sock.recv(65536)
            frames, _errors = decoder.feed(data)
            assert json.loads(frames[0])["ok"] is True
        error = read_until(alice, "error")
        assert error["code"] == "kicked"


def test_leave_when_not_in_room_returns_error(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "leave", "room": "general"})
        error = read_until(alice, "error")
        assert error["code"] == "room_not_found"


def test_idle_eviction_emits_idle_timeout_error(tmp_path) -> None:
    clock = ManualClock()
    server = ChatServer(
        ServerConfig(
            host="127.0.0.1",
            port=0,
            db_path=str(tmp_path / "chat.db"),
            heartbeat_interval=1000.0,
            idle_timeout=10.0,
        ),
        clock=clock,
    )
    server.start()
    try:
        alice = connect_raw(server, "alice")
        clock.advance(11.0)
        server.evict_idle_sessions()
        error = read_until(alice, "error")
        assert error["code"] == "idle_timeout"
    finally:
        server.stop()


def _read_until(sock: socket.socket, msg_type: str, *, timeout: float = 3.0) -> dict[str, object]:
    decoder = FrameDecoder(1 << 20)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            data = sock.recv(65536)
        except TimeoutError:
            continue
        if not data:
            break
        frames, _errors = decoder.feed(data)
        for frame in frames:
            message = json.loads(frame)
            if message.get("type") == msg_type:
                return message
    raise AssertionError(f"no {msg_type!r} frame before timeout")


def test_handshake_timeout_emits_error_frame(tmp_path) -> None:
    clock = ManualClock()
    server = ChatServer(
        ServerConfig(
            host="127.0.0.1",
            port=0,
            db_path=str(tmp_path / "chat.db"),
            heartbeat_interval=1000.0,
            idle_timeout=5000.0,
            handshake_timeout=10.0,
        ),
        clock=clock,
    )
    server.start()
    try:
        sock = socket.create_connection(server.address, timeout=2.0)
        sock.settimeout(0.5)
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and server.snapshot()["connected_clients"] != 1:
                time.sleep(0.02)
            clock.advance(11.0)
            server.evict_idle_sessions()
            assert server.snapshot()["handshake_timeouts"] == 1
            error = _read_until(sock, "error")
            assert error["code"] == "handshake_timeout"
        finally:
            sock.close()
    finally:
        server.stop()


def test_pong_is_rate_limited(tmp_path) -> None:
    with running_server(tmp_path, rate_limit_messages=1, rate_limit_window=60.0) as server:
        alice = connect_raw(server, "alice")
        send_frame(alice, {"type": "pong", "nonce": "n1"})
        send_frame(alice, {"type": "pong", "nonce": "n2"})
        error = read_until(alice, "error")
        assert error["code"] == "rate_limited"


def test_db_job_failure_rolls_back_cache(tmp_path) -> None:
    server = ChatServer(
        ServerConfig(host="127.0.0.1", port=0, db_path=str(tmp_path / "chat.db")),
    )
    server.start()
    try:
        message = chat_frame(
            message_id=new_message_id(),
            room="general",
            sender="alice",
            body="doomed",
            session_id="s_test",
        )
        server.history_cache.append("general", message)
        assert server.history_cache.get("general") is not None
        server._on_db_job_failure(DbJob("store_message", {"message": message}))
        cached = server.history_cache.get("general")
        assert cached is None or not any(item.get("message_id") == message["message_id"] for item in cached)
    finally:
        server.stop()


def test_rejects_history_limit_above_room_cache() -> None:
    with pytest.raises(ValueError, match="history_limit must be <= room_cache_messages"):
        ServerConfig(history_limit=100, room_cache_messages=50)


def test_apply_migrations_raises_for_intermediate_version(monkeypatch) -> None:
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 3)
    with pytest.raises(NotImplementedError, match="user_version=1"):
        migrations._apply_migrations(None, 1)  # type: ignore[arg-type]


def test_store_message_rejects_bad_sender_and_metadata(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "chat.db")
    store.initialize()
    conn = store.connect()
    base = {
        "message_id": new_message_id(),
        "kind": "chat",
        "room": "general",
        "body": "hi",
        "server_timestamp": utc_timestamp(),
    }
    try:
        store.create_room(conn, "general")
        with pytest.raises(ValueError, match="sender"):
            store.store_message(conn, {**base, "sender": 42})
        with pytest.raises(ValueError, match="metadata"):
            store.store_message(conn, {**base, "sender": "alice", "metadata": "bad"})
        with pytest.raises(ValueError, match="unsupported message kind"):
            store.store_message(conn, {**base, "sender": "alice", "kind": "fax"})
    finally:
        conn.close()
