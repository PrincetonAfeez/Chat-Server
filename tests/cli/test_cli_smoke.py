from __future__ import annotations

from chatserver.cli.main import server_main


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
