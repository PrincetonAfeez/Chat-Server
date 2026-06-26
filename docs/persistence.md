# Persistence

SQLite is initialized with:

```powershell
chatserver init-db --db chat.db
```

The schema stores:

- known users
- rooms
- messages
- audit events

All writes flow through `DbWriter`, a single background writer thread fed by a
bounded priority queue. Network handlers enqueue `DbJob` instances and never
perform SQLite writes directly. Jobs are applied highest-`priority`-first (FIFO
within a band); transient `sqlite3.OperationalError`s are retried up to three
times, while permanent errors are logged to a bounded failures ring and dropped.

History reads use `SQLiteStore.recent_room_messages()` and warm `HistoryCache` on
cache misses. The cache is not durable truth. A successful `prune_history` job
invalidates the in-memory cache so `/history` cannot serve rows SQLite has already
dropped.

Retention is enforced by a single scheduled `prune_history` job that keeps the
most recent `history_retention_count` messages **per room across every room in
the database** (not just rooms with live members). Ordering uses
`server_timestamp` with a `rowid` tiebreaker, so messages sharing a timestamp
prune and replay deterministically.

The schema sets `PRAGMA user_version = 1`; `init-db` is idempotent
(`CREATE TABLE IF NOT EXISTS`) and safe to run repeatedly.

Notes:

- Pruning uses a SQL window function (`ROW_NUMBER() OVER (PARTITION BY room …)`),
  which requires SQLite ≥ 3.25 (bundled with Python 3.11+).
- Direct messages are **not persisted**. They are best-effort live delivery
  only; the durable record is room history. The `dm_sent` structured log is the
  audit trail, so private message bodies never land in the database.
