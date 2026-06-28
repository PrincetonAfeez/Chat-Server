""" Test polish """

from __future__ import annotations

import argparse
import io
import socket
from pathlib import Path

import pytest

from chatserver.cli.commands import admin as admin_cmd
from chatserver.config import ServerConfig
from chatserver.network.client import ChatClient
from chatserver.network.server import ChatServer
from chatserver.observability.stats import ServerStats
from chatserver.persistence.sqlite_store import SQLiteStore
from chatserver.persistence.writer import DbWriter
from chatserver.queues.db_jobs import DbJob
from conftest import connect_raw, read_until, running_server, send_frame


def test_json_config_loads_server_section() -> None:
    config_path = Path(__file__).resolve().parents[2] / "examples" / "chatserver.json"
    config = ServerConfig.from_file(config_path)
    assert config.port == 9000
    assert config.history_limit == 50


def test_prune_success_applies_retention_to_cache(tmp_path) -> None:
    server = ChatServer(ServerConfig(host="127.0.0.1", port=0, db_path=str(tmp_path / "chat.db")))
    messages = [{"message_id": f"m{i}", "body": str(i)} for i in range(10)]
    server.history_cache.warm("general", messages)
    assert server.history_cache.get("general") is not None
    server._on_db_job_success(DbJob("prune_history", {"keep_count": 3}))
    assert server.history_cache.get("general") is None


def test_rename_rolls_back_when_db_queue_full(tmp_path) -> None:
    with running_server(tmp_path, db_queue_size=2) as server:
        alice = connect_raw(server, "alice")
        server.db_writer.enqueue(DbJob("create_room", {"room": "fill1"}, priority=1))
        server.db_writer.enqueue(DbJob("create_room", {"room": "fill2"}, priority=1))
        send_frame(alice, {"type": "hello", "nick": "alice2"})
        error = read_until(alice, "error")
        assert error["code"] == "server_busy"
        session = server.nicks.get("alice")
        assert session is not None
        assert session.nick == "alice"


def test_client_connect_surfaces_nick_taken(tmp_path) -> None:
    with running_server(tmp_path) as server:
        host, port = server.address
        first = socket.create_connection((host, port), timeout=2.0)
        send_frame(first, {"type": "hello", "nick": "alice"})
        read_until(first, "welcome")
        client = ChatClient(host=host, port=port, nick="alice", output=io.StringIO())
        with pytest.raises(RuntimeError, match="nick_taken"):
            client.connect()
        client.close()
        first.close()


def test_admin_live_stats_table_format(tmp_path, capsys) -> None:
    with running_server(tmp_path, admin_enabled=True, admin_port=0) as server:
        host, port = server.admin_address
        assert port is not None
        connect_raw(server, "alice")
        args = argparse.Namespace(
            admin_command="stats",
            host=host,
            port=port,
            db=str(tmp_path / "chat.db"),
            format="table",
        )
        assert admin_cmd.admin(args) == 0
        out = capsys.readouterr().out
        assert "connected_clients" in out


def test_db_writer_join_returns_true_when_stopped(tmp_path) -> None:
    stats = ServerStats()
    store = SQLiteStore(tmp_path / "chat.db")
    writer = DbWriter(store, maxsize=10, stats=stats)
    assert writer.join(1.0) is True
    writer.start()
    writer.stop(drain=False)
    assert writer.join(1.0) is True


def test_leave_not_in_room_increments_rejected_messages(tmp_path) -> None:
    with running_server(tmp_path) as server:
        alice = connect_raw(server, "alice")
        before = server.snapshot()["rejected_messages"]
        send_frame(alice, {"type": "leave", "room": "general"})
        read_until(alice, "error")
        assert server.snapshot()["rejected_messages"] == before + 1
