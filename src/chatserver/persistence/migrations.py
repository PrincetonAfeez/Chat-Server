from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path


def init_db(db_path: str | Path) -> None:
    schema = files("chatserver.persistence").joinpath("schema.sql").read_text(encoding="utf-8")
    path = Path(db_path)
    if path.parent and str(path.parent) != ".":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
