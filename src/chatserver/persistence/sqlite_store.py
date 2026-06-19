from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from chatserver.protocol.messages import utc_timestamp

from .migrations import init_db


class SQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    def initialize(self) -> None:
        init_db(self.db_path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def upsert_user(self, conn: sqlite3.Connection, nick: str) -> None:
        ts = utc_timestamp()
        conn.execute(
            """
            INSERT INTO users(nick, first_seen, last_seen)
            VALUES (?, ?, ?)
            ON CONFLICT(nick) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (nick, ts, ts),
        )

    def create_room(self, conn: sqlite3.Connection, room: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO rooms(name, created_at) VALUES (?, ?)",
            (room, utc_timestamp()),
        )

    def store_message(self, conn: sqlite3.Connection, message: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO messages(
                message_id, kind, room, sender, recipient, body, server_timestamp, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message["message_id"],
                message.get("kind", message.get("type", "chat")),
                message.get("room"),
                message.get("sender", "system"),
                message.get("recipient") or message.get("to"),
                message["body"],
                message["server_timestamp"],
                json.dumps(message.get("metadata", {}), sort_keys=True),
            ),
        )

    def record_event(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        *,
        nick: str | None = None,
        room: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO events(event_type, nick, room, details_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, nick, room, json.dumps(details or {}, sort_keys=True), utc_timestamp()),
        )

    def prune_history(self, conn: sqlite3.Connection, keep_count: int, *, room: str | None = None) -> None:
        """Keep only the most recent ``keep_count`` messages per room.

        With ``room=None`` every room in the table is pruned in a single pass,
        including rooms that no longer have live members. The ``rowid``
        tiebreaker makes ordering deterministic when timestamps collide.
        """
        if room is None:
            conn.execute(
                """
                DELETE FROM messages
                WHERE rowid IN (
                    SELECT rowid FROM (
                        SELECT rowid,
                               ROW_NUMBER() OVER (
                                   PARTITION BY room
                                   ORDER BY server_timestamp DESC, rowid DESC
                               ) AS rn
                        FROM messages
                        WHERE room IS NOT NULL
                    )
                    WHERE rn > ?
                )
                """,
                (keep_count,),
            )
            return
        conn.execute(
            """
            DELETE FROM messages
            WHERE room = ?
              AND rowid NOT IN (
                  SELECT rowid
                  FROM messages
                  WHERE room = ?
                  ORDER BY server_timestamp DESC, rowid DESC
                  LIMIT ?
              )
            """,
            (room, room, keep_count),
        )

    def recent_room_messages(self, room: str, limit: int) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            rows = conn.execute(
                """
                SELECT message_id, kind, room, sender, recipient, body, server_timestamp
                FROM messages
                WHERE room = ? AND kind IN ('chat', 'system')
                ORDER BY server_timestamp DESC, rowid DESC
                LIMIT ?
                """,
                (room, limit),
            ).fetchall()
        finally:
            conn.close()
        messages: list[dict[str, Any]] = []
        for row in reversed(rows):
            message = {
                "type": row["kind"] if row["kind"] == "chat" else "system",
                "message_id": row["message_id"],
                "kind": row["kind"],
                "room": row["room"],
                "sender": row["sender"],
                "body": row["body"],
                "server_timestamp": row["server_timestamp"],
            }
            if row["recipient"]:
                message["recipient"] = row["recipient"]
            messages.append(message)
        return messages

    def db_stats(self) -> dict[str, int]:
        conn = self.connect()
        try:
            return {
                "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "rooms": conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0],
                "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            }
        finally:
            conn.close()

    def rooms(self) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            rows = conn.execute(
                """
                SELECT rooms.name, COUNT(messages.message_id) AS message_count
                FROM rooms
                LEFT JOIN messages ON messages.room = rooms.name
                GROUP BY rooms.name
                ORDER BY rooms.name
                """
            ).fetchall()
        finally:
            conn.close()
        return [{"room": row["name"], "messages": row["message_count"]} for row in rows]
