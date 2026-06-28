""" Test CLI smoke """

from __future__ import annotations

import pytest

from chatserver import __version__
from chatserver.cli.main import client_main, server_main
from pathlib import Path


def test_server_version_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        server_main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_client_version_flag(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        client_main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_init_db_and_admin_stats(tmp_path, capsys) -> None:
    db = tmp_path / "chat.db"
    assert server_main(["init-db", "--db", str(db)]) == 0
    assert db.exists()
    assert server_main(["admin", "stats", "--db", str(db)]) == 0
    captured = capsys.readouterr()
    assert '"messages": 0' in captured.out


def test_demo_framing_runs(capsys) -> None:
    assert server_main(["demo", "framing"]) == 0
    captured = capsys.readouterr()
    assert "frames" in captured.out


def test_serve_missing_config_exits_2(capsys) -> None:
    assert server_main(["serve", "--config", "does-not-exist.toml"]) == 2
    assert "file not found" in capsys.readouterr().err


def test_serve_loads_config_file(tmp_path) -> None:
    config_path = tmp_path / "custom.toml"
    db_path = tmp_path / "chat.db"
    config_path.write_text(
        f'[server]\nhost = "127.0.0.1"\nport = 0\ndb_path = "{db_path.as_posix()}"\n',
        encoding="utf-8",
    )
    from chatserver.cli.commands.server import _config_from_args
    import argparse

    args = argparse.Namespace(
        config=str(config_path),
        host=None,
        port=None,
        db_path=None,
        engine=None,
        max_connections=None,
        max_message_size=None,
        outbound_queue_size=None,
        outbound_backpressure_policy=None,
        db_queue_size=None,
        db_backpressure_policy=None,
        heartbeat_interval=None,
        idle_timeout=None,
        handshake_timeout=None,
        history_limit=None,
        history_retention_count=None,
        event_retention_count=None,
        room_cache_messages=None,
        max_cached_rooms=None,
        cache_ttl=None,
        rate_limit_messages=None,
        rate_limit_window=None,
        stats_interval=None,
        shutdown_timeout=None,
        admin_host=None,
        admin_port=None,
        admin_enabled=None,
        log_level=None,
    )
    config = _config_from_args(args)
    assert Path(config.db_path) == db_path


def test_offline_admin_rooms_reports_message_count(tmp_path, capsys) -> None:
    from chatserver.persistence.sqlite_store import SQLiteStore
    from chatserver.protocol.messages import new_message_id, utc_timestamp

    db = tmp_path / "chat.db"
    assert server_main(["init-db", "--db", str(db)]) == 0
    store = SQLiteStore(db)
    conn = store.connect()
    try:
        store.create_room(conn, "general")
        store.store_message(
            conn,
            {
                "message_id": new_message_id(),
                "kind": "chat",
                "room": "general",
                "sender": "alice",
                "body": "hello",
                "server_timestamp": utc_timestamp(),
            },
        )
        conn.commit()
    finally:
        conn.close()
    assert server_main(["admin", "rooms", "--db", str(db), "--format", "json"]) == 0
    captured = capsys.readouterr()
    assert '"message_count": 1' in captured.out


def test_configure_logging_applies_level() -> None:
    import logging

    from chatserver.observability.logging import configure_logging

    configure_logging("WARNING")
    assert logging.getLogger().getEffectiveLevel() == logging.WARNING


def test_admin_clients_without_port_exits_2(capsys) -> None:
    assert server_main(["admin", "clients", "--db", "chat.db"]) == 2
    assert "needs a live server" in capsys.readouterr().out


def test_serve_non_threaded_engine_exits_2(capsys, tmp_path) -> None:
    db = tmp_path / "chat.db"
    assert server_main(["init-db", "--db", str(db)]) == 0
    assert server_main(["serve", "--db", str(db), "--engine", "asyncio", "--port", "0"]) == 2
    assert "threaded" in capsys.readouterr().err
