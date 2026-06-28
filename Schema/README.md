# Schema

This folder contains simple SQLite schema files for the Chat Server project.

## Files

- `schema.sql` — complete database schema in one file.
- `users.sql` — users table.
- `rooms.sql` — rooms table.
- `messages.sql` — messages table and message indexes.
- `events.sql` — events table and event indexes.
- `indexes.sql` — all indexes in one place.

## Usage

Create or initialize a database with:

```bash
sqlite3 chat.db < Schema/schema.sql
```

The schema is aligned with the project’s SQLite persistence layer.
