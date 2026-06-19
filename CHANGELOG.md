# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-19

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

[Unreleased]: https://example.com/compare/v0.1.0...HEAD
[0.1.0]: https://example.com/releases/tag/v0.1.0
