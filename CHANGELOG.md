# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- History cache marks post-eviction entries incomplete so `/history` re-reads SQLite.
- Pending+DB history merge deduplicates by `message_id`; `warm()` merges with concurrent appends.
- Cache-hit `/history` merges pending DB writes; cache sized for `max(room_cache_messages, history_limit)`.
- Failed DB writes roll back optimistic cache appends via `on_job_failure`.
- `DbWriter.stop()`/`join(timeout)` honor shutdown timeout; queue cleared when `drain=False`.
- Idle/handshake evictions emit wire errors and idle evictions enqueue `record_eviction`.
- `pong` subject to rate limiter; handshake `upsert_user` enqueue failure rejects nick.
- Client waits for `welcome` on connect; scoped pending-state clearing on errors.
- `drop_*` outbound send timeout emits `slow_client` error before close.
- Config cross-validation: `history_limit <= room_cache_messages`, retention bounds.
- `store_message` validates sender/metadata/kind; migration stub raises for intermediate versions.
- Shutdown disconnect reason records `SERVER_SHUTDOWN` for idle clients at stop.
- Writer send timeout triggers `slow_client` eviction under `disconnect` policy.
- CLI defers `current_room` and local `nick` until server ack on leave/rename.
- Server clamps wire `history` limit to `history_limit`; admin bind restricted to localhost.
- `kick` uses dedicated `kicked` error code; `DbWriter.stop(drain=False)` honored.
- Signal handler flag reset on each `serve`; schema sanity check on DB open.

### Changed

- `make check` runs format-check and coverage gate; README documents config file and admin JSON shapes.
- `demo basic` consumes join history frames like `demo multi-client`.

### Polished

- History cache invalidated after successful DB prune; rename rolls back on DB queue full.
- Eviction paths consolidated; handshake timeouts enqueue `record_eviction`.
- Retention prune jobs retry once on queue full; DB writer join timeout logged on shutdown.
- Client `connect()` surfaces server errors; `rejected_messages` aligned across reject paths.
- `PROTOCOL.md` documents `idle_timeout` / `handshake_timeout`; added `examples/chatserver.json`.
- `pytest-timeout` (120s) added; README notes Windows slow-suite exit behavior.

### Polished (round 2)

- Handshake/join `server_busy` is non-recoverable; client `connect()` fails on `server_busy`.
- Join rolls back live membership when both audit enqueues drop; partial drops logged.
- Cache `apply_retention()` after prune; scheduler/admin/accept shutdown join timeouts logged.
- `ConnectionState` reserved labels documented; lifecycle/PROTOCOL doc sync.

## [0.1.0] - 2026-06-19

### Fixed (Round 2)

- `history` limit rejects JSON booleans; `store_message` validates `server_timestamp`.
- `stop()` always sets `_stop_complete`; admin shutdown uses `shutdown_timeout`.
- System notices broadcast live even when DB persist fails (cache skipped).
- Re-join ack; client defers `current_room` until server confirms join.
- Admin bind restricted to localhost; signal handler re-entrancy guard.
- Offline admin `rooms` uses `message_count` field; removed dead `store_system_event` job.
- `server_shutting_down` error sent with `send_immediate` so clients see it before close.

### Fixed (Round 1)

- Shutdown ordering: stop accept loop and scheduler before session teardown; re-entrant `stop()` waits for completion; log join timeouts.
- Client send lock and pong I/O error handling; `/history` limit-only parsing.
- DB backpressure symmetry for system notices (composite persistence job); pending-queue merge on history cache miss; metadata round-trip from SQLite.
- Schema init respects `PRAGMA user_version`; duplicate `message_id` inserts fail instead of silent replace.
- Protocol: `presence` handler, history membership check, UTF-8 body size validation, bounded `pong.nonce`, `slow_client` error before eviction.
- Config/CLI: `log_level` applied, missing config file handling, port/log-level validation, additional serve flags.
- Scheduler job deduplication on restart; thread-safe rate limiter and outbound `drop_oldest`; DB writer shutdown guard.
- Cache eviction metrics unified via `HistoryCache` callback.

### Changed

- `KNOWN_ENGINES` restricted to `threaded` until stretch engines ship.
- Documentation aligned with idle-timeout semantics, DB backpressure scope, and join auto-history behavior.

### Added

- Threaded raw-TCP chat server library and CLI: JSON Lines framing with partial/
  merged-read handling, protocol validation with stable error codes, and a
  thread-per-connection engine behind a `ServerEngine` seam.
- Messaging: rooms (join/leave/who/rooms), broadcast, direct messages, slash
  commands, server-assigned message ids/timestamps.
- Backpressure: bounded per-client outbound queues with configurable policy
  (`disconnect` / `drop_oldest` / `drop_newest`); single SQLite writer fed by a
  bounded priority queue with `reject_chat` / `disconnect` policy.
- Persistence: SQLite with idempotent schema init (`PRAGMA user_version`),
  message history with per-room retention, and bounded audit-event retention.
- Caching: in-memory per-room history cache with TTL/LRU bounds, warmed from
  SQLite on miss.
- Lifecycle: handshake, heartbeats, idle timeout, anti-slowloris handshake
  timeout, max-connections cap, graceful shutdown with signal handling.
- Observability: structured JSON logging, server stats (rolling messages/sec,
  queue depths, DB backlog, cache and eviction counters), and a localhost admin
  control socket (stats/clients/rooms/queues/cache/evictions/kick/broadcast).
- CLI: `chatserver` (init-db / serve / admin / demo) and `chatclient` (connect),
  plus runnable feature and "unsafe" teaching demos. Both expose `--version`.
- Hardening: per-frame exception resilience, control-character/terminal-escape
  rejection in message bodies, property-based fuzzing of the frame decoder.
- Tooling: `mypy --strict`, `ruff`, `pytest` with a coverage gate, pinned dev
  toolchain (`requirements-dev.txt`), and GitHub Actions CI on Python 3.11-3.13.

### Security

- Binds to localhost by default. Plaintext TCP with no authentication or TLS;
  public exposure would require auth, TLS, and abuse controls (out of scope).

[Unreleased]: https://github.com/prince/chat-server/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/prince/chat-server/releases/tag/v0.1.0
