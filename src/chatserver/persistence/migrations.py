""" Migrations for the chat server library """

from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

SCHEMA_VERSION = 1
_EXPECTED_TABLES = ("users", "rooms", "messages", "events")


def _verify_schema(conn: sqlite3.Connection) -> None:
    for table in _EXPECTED_TABLES:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if row is None:
            raise ValueError(f"database missing required table: {table}")


def _apply_migrations(conn: sqlite3.Connection, current: int) -> None:
    """Incremental migrations for ``current + 1 .. SCHEMA_VERSION``.

    v1 is the baseline applied from ``schema.sql``. Add ``_migrate_to_N``
    functions here when bumping ``SCHEMA_VERSION``.
    """
    if 0 < current < SCHEMA_VERSION:
        raise NotImplementedError(
            f"database at user_version={current} requires migration to {SCHEMA_VERSION}; "
            "implement _apply_migrations or delete chat.db for local dev"
        )


def init_db(db_path: str | Path) -> None:
    """Create or open the database at ``SCHEMA_VERSION``.

    Existing databases at the current version are verified and left unchanged.
    To apply a future schema change, bump ``SCHEMA_VERSION`` and add a step in
    ``_apply_migrations`` (deleting ``chat.db`` also works for local dev).
    """
    path = Path(db_path)
    if path.parent and str(path.parent) != ".":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        current = int(row[0]) if row else 0
        if current >= SCHEMA_VERSION:
            _verify_schema(conn)
            return
        if current == 0:
            schema = files("chatserver.persistence").joinpath("schema.sql").read_text(encoding="utf-8")
            conn.executescript(schema)
        else:
            _apply_migrations(conn, current)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        _verify_schema(conn)
    finally:
        conn.close()
