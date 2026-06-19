# Chat Server Library

<!-- After publishing to GitHub, add a live CI badge:
![CI](https://github.com/<you>/<repo>/actions/workflows/ci.yml/badge.svg) -->
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Type-checked: mypy --strict](https://img.shields.io/badge/mypy-strict-blue)
![Lint: ruff](https://img.shields.io/badge/lint-ruff-purple)
![Tests: pytest](https://img.shields.io/badge/tests-pytest-green)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

A reusable Python chat server library plus CLI server and CLI client using raw TCP sockets and JSON Lines framing.

This build implements the reliable threaded version first: one accept thread, one reader thread and one writer thread per connected client, bounded per-client outbound queues, a single SQLite writer thread, in-memory room history cache, scheduler-driven heartbeats/idle eviction, rate limiting, structured errors, and deterministic tests.

## Contents

- [Quick Start](#quick-start)
- [CLI](#cli)
- [Exit Codes](#exit-codes)
- [Concurrency Model](#concurrency-model)
- [Lifecycle Of One Chat Message](#lifecycle-of-one-chat-message)
- [Backpressure](#backpressure)
- [Persistence](#persistence)
- [Tests](#tests)
- [Security Note](#security-note)
- Design docs: [architecture](docs/architecture.md) · [concurrency](docs/concurrency_models.md) · [protocol](PROTOCOL.md) · [backpressure](docs/backpressure.md) · [lifecycle](docs/lifecycle.md) · [persistence](docs/persistence.md)

## Quick Start

```powershell
python -m pip install -e ".[dev]"
chatserver init-db --db chat.db
chatserver serve --host 127.0.0.1 --port 9000 --db chat.db
```

The runtime has no third-party dependencies (standard library only). For a
reproducible dev/test environment with the exact locked toolchain:

```powershell
python -m pip install -e . -r requirements-dev.txt
```

In another terminal:

```powershell
chatclient connect --host 127.0.0.1 --port 9000 --nick princeton
```

Client commands:

```text
/join general
/rooms
/who general
/msg ada hello
/history general 25
/leave general
/nick newname
/quit
```

Plain lines (without a leading `/`) are sent to your **current room**, which is
set by `/join` and cleared by leaving it. Join a room before typing, or the
client will remind you to.

## CLI

Server:

```powershell
chatserver serve `
  --host 127.0.0.1 `
  --port 9000 `
  --db chat.db `
  --engine threaded `
  --max-connections 100 `
  --max-message-size 4096 `
  --outbound-queue-size 100 `
  --db-queue-size 1000
```

Live admin (enable the localhost control socket with `--admin-port`, then query it):

```powershell
chatserver serve --db chat.db --admin-port 9001
chatserver admin stats     --port 9001
chatserver admin clients   --port 9001
chatserver admin queues    --port 9001
chatserver admin cache     --port 9001
chatserver admin evictions --port 9001
chatserver admin kick      --nick ada --port 9001
chatserver admin broadcast --message "restart in 5 minutes" --port 9001
```

Without `--port`, `admin stats` and `admin rooms` fall back to reading durable
counts straight from the DB file:

```powershell
chatserver admin stats --db chat.db
chatserver admin rooms --db chat.db
```

The admin socket binds to localhost and is unauthenticated — it is a local
operations tool, not a public interface.

Teaching / feature demos (each spins up an ephemeral server and tears it down):

```powershell
chatserver demo framing
chatserver demo basic
chatserver demo slow-client
chatserver demo rate-limit
chatserver demo idle-timeout
chatserver demo db-writer
chatserver demo graceful-shutdown
chatserver demo all
chatserver demo unsafe-framing
chatserver demo unsafe-slow-client
chatserver demo unsafe-room-race
chatserver demo unsafe-db-blocking
chatserver demo unsafe-shutdown
```

The `unsafe-*` demos actually run the broken pattern (e.g. a lockless set
mutated mid-iteration, a blocking broadcast, a leaked worker thread) and print
the failure next to the safe behavior.

## Exit Codes

`chatserver` and `chatclient` use consistent, conventional exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Runtime error (e.g. failed to bind the port, DB file not found, admin socket unreachable) |
| `2` | Usage or configuration error (bad arguments, invalid config value, a live-only admin command run without `--port`) |
| `130` | Interrupted by `Ctrl-C` / `SIGINT` |

Both commands also support `--version`.

## Concurrency Model

The implemented engine is thread-per-connection. The central tradeoff this
project exists to demonstrate:

| Model | Scales by | Cost | Shared-state safety | Must never |
| --- | --- | --- | --- | --- |
| **thread-per-connection** (this build) | one OS thread per client | a thread + stack per connection; context-switch overhead at high counts | locks around registries/rooms/cache | hold a lock across blocking I/O |
| selectors event loop (stretch) | one thread, many sockets via `select`/`epoll` | cheap idle connections; manual readiness bookkeeping | single-threaded — no locks needed | block the loop |
| asyncio (stretch) | one event loop, `async` handlers | cheap idle connections; ergonomic | single-threaded — no locks needed | call blocking code without `to_thread` |

Thread-per-connection is simple and easy to debug, and makes slow-client
isolation concrete (each client has its own writer thread + bounded queue). It
costs a thread per client, which is why the stretch engines exist behind the
same `ServerEngine` interface. See [docs/concurrency_models.md](docs/concurrency_models.md).

Each accepted client gets:

- one reader thread that receives bytes, feeds the frame decoder, validates protocol messages, and calls server handlers
- one writer thread that drains that client's bounded outbound queue and writes JSON Lines frames to the socket
- a per-session rate limiter and lifecycle state

Shared live state is protected by `RLock`s:

- connected session registry
- active nickname registry
- room membership
- the per-room history cache
- stats counters

Broadcast routing snapshots room membership under lock, then releases the lock before enqueueing outbound messages. That avoids mutating room state while iterating and prevents one slow client from blocking delivery to other clients.

Two further safeguards keep the threaded model honest:

- Each session has a `send_lock`, so the writer thread and any direct
  `send_immediate` (shutdown notice, fatal framing error) cannot interleave
  bytes on the same socket.
- Scheduled jobs are isolated: a job that raises is logged and skipped, so one
  failure never kills the scheduler thread that also drives heartbeats, idle
  eviction, pruning, and cache cleanup.

## Lifecycle Of One Chat Message

1. The session reader thread receives arbitrary TCP bytes.
2. `FrameDecoder` buffers partial frames and splits complete newline-delimited JSON frames.
3. `validate_client_message()` parses JSON, rejects invalid types/fields, and enforces handshake state.
4. The server checks room membership and the per-client rate limiter.
5. The server assigns `message_id`, timestamp, sender, and metadata.
6. The message is enqueued to the bounded DB writer queue.
7. The room history cache is updated immediately.
8. Room members are snapshotted and each recipient gets an outbound queue enqueue.
9. Each recipient writer thread sends the frame independently.
10. Stats and structured logs are updated.

## Backpressure

Live delivery is best effort. Every connected client has a bounded outbound queue. The `outbound_backpressure_policy` setting decides what happens on overflow:

- `disconnect` (default) — close the slow session, clean up its rooms, record an eviction, and keep routing to everyone else.
- `drop_oldest` — discard the oldest queued message to make room for the new one.
- `drop_newest` — drop the incoming message.

SQLite writes also use a bounded queue. `db_backpressure_policy` is `reject_chat` by default: if the DB writer queue is full, the server returns a structured `server_busy` error and does not route or cache the new message (`disconnect` evicts the offending session instead). DB jobs are processed highest-priority-first so chat persistence is never starved by low-priority audit events. Both policies are validated at startup and surfaced in diagnostics. See [docs/backpressure.md](docs/backpressure.md).

## Persistence

SQLite is the default backend. All persistent writes go through one `DbWriter` thread:

- `store_message`
- `upsert_user`
- `create_room`
- `record_join`
- `record_leave`
- `record_disconnect`
- `record_eviction`
- `prune_history`
- `store_system_event`

Room history reads are allowed from SQLite and are used to warm the cache on cache miss. Direct messages are best-effort live delivery only and are not persisted (the durable record is room history).

## Tests

```powershell
python -m pytest
```

The suite covers framing, protocol validation, config validation, rate limiting
(unit and end-to-end over a socket), the bounded outbound queue and its
`drop_oldest` policy, cache bounds, **cache + scheduler concurrency safety**,
multi-client chat, rooms, DMs, history, cache **warmup-from-SQLite**, handshake
rejection, max connections, idle eviction with an injected clock, **disconnect
cleanup**, **history pruning**, the admin control socket, graceful shutdown
cleanup with a **no-leaked-threads** assertion, DB writer queue behavior, CLI
smoke paths, and the unsafe teaching demonstrations (which assert the failure is
actually reproduced).

## Security Note

The default bind address is `127.0.0.1`. Exposing this server publicly would require authentication, TLS, abuse controls, stronger authorization, and additional protocol hardening.
