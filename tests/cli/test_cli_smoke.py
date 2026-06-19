from __future__ import annotations

import pytest

from chatserver import __version__
from chatserver.cli.main import client_main, server_main


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
