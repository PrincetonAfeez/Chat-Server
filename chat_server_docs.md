# Architecture Decision Record
## App — Chat Server
**Realtime Messaging Systems Group | Document 1 of 5**
**Status: Accepted**

---

## Context

The Realtime Messaging Systems group requires a reusable Python chat server library with a CLI server and CLI client. The project must demonstrate raw TCP sockets, JSON Lines framing, message validation, thread-per-connection concurrency, per-client outbound backpressure, SQLite persistence, in-memory history caching, room routing, heartbeats, idle eviction, rate limiting, live diagnostics, and unsafe teaching demos that explain why the safe design exists.

The system is intentionally not a production public chat platform. Its default bind address is localhost, the admin socket is localhost-only and unauthenticated, and public exposure would require authentication, authorization, TLS, abuse controls, and operational hardening outside this V1 scope.

The selected architecture is a threaded raw-socket server. One accept thread listens for clients. Each connected client owns one reader thread and one writer thread. The reader receives arbitrary TCP bytes, decodes JSON Lines frames, validates protocol messages, and dispatches them to the server. The writer drains a bounded outbound queue and writes encoded JSON frames to the socket. Durable writes are serialized through one SQLite writer thread.

---

## Decisions

### Decision 1 — Use raw TCP sockets with JSON Lines framing

**Chosen:** Implement the wire protocol as newline-delimited JSON objects over TCP.

**Rejected:** WebSockets, HTTP long polling, gRPC, or a third-party realtime framework.

**Reason:** The project is a networking/concurrency capstone. Raw sockets make TCP behavior, partial frames, merged frames, buffer limits, and graceful shutdown visible.

---

### Decision 2 — Implement the reliable threaded engine first

**Chosen:** Ship the thread-per-connection engine as the implemented V1 engine.

**Rejected:** Starting with selectors or asyncio.

**Reason:** Thread-per-connection is easier to explain and debug. It also makes slow-client isolation concrete: each client has its own writer thread and bounded outbound queue. Selectors and asyncio remain stretch engines behind the same engine interface.

---

### Decision 3 — Give every session a reader thread and writer thread

**Chosen:** Each accepted client gets:

- one reader thread for `recv -> FrameDecoder -> validate -> server handler`
- one writer thread for `outbound queue -> encode_frame -> sendall`

**Rejected:** Having handler threads write directly to sockets whenever they broadcast.

**Reason:** Direct writes from many threads can interleave bytes and corrupt the JSON Lines stream. A dedicated writer thread per session provides one serialized path for normal outbound messages.

---

### Decision 4 — Use a per-session send lock for all socket writes

**Chosen:** Protect both writer-thread `sendall` and direct `send_immediate` calls with `send_lock`.

**Rejected:** Trusting that only the writer thread writes to the socket.

**Reason:** Some conditions require immediate frames, such as fatal framing errors or shutdown notices. The send lock prevents immediate frames and queued frames from interleaving bytes.

---

### Decision 5 — Use bounded per-client outbound queues

**Chosen:** Every session owns a bounded outbound queue with configurable overflow policy.

Policies:
- `disconnect`
- `drop_oldest`
- `drop_newest`

**Rejected:** Unbounded queues or blocking broadcasts.

**Reason:** A slow client must not consume unbounded memory or block delivery to healthy clients. Bounded queues make backpressure explicit and testable.

---

### Decision 6 — Snapshot room membership before broadcasting

**Chosen:** Room membership is snapshotted under lock, then the server releases locks before enqueueing messages.

**Rejected:** Holding a room lock while enqueueing to every recipient.

**Reason:** Enqueueing can trigger slow-client eviction and other side effects. Locks should protect shared state only briefly and must not be held across potentially blocking I/O or cascading operations.

---

### Decision 7 — Use SQLite as the durable history backend

**Chosen:** Store users, rooms, room chat/system messages, and audit events in SQLite.

**Rejected:** In-memory-only history.

**Reason:** Durable room history is central to the chat server. SQLite is standard-library accessible and sufficient for a local educational server.

---

### Decision 8 — Serialize persistent writes through one DB writer thread

**Chosen:** All SQLite writes are represented as `DbJob` objects and processed by one `DbWriter` thread.

**Rejected:** Letting every client thread write to SQLite independently.

**Reason:** SQLite write concurrency is limited. A single writer thread avoids scattered write locks and gives the server one place to apply retry, priority, backpressure, and pending-message tracking.

---

### Decision 9 — Use priority DB jobs

**Chosen:** Process the DB writer queue highest-priority-first with FIFO ordering within priority.

**Rejected:** One plain FIFO queue for all persistence work.

**Reason:** Chat persistence should not be starved by lower-priority audit events. The writer can prioritize message storage while still accepting best-effort audits.

---

### Decision 10 — Reject or disconnect on DB writer backpressure

**Chosen:** If the DB writer queue is full, chat messages are not routed or cached. The default policy returns a structured `server_busy` error; an alternate policy disconnects the sender.

**Rejected:** Routing live messages that failed to persist.

**Reason:** Room chat history is the durable record. If storage cannot accept the message, the server must not pretend the room message happened.

---

### Decision 11 — Keep direct messages live-only

**Chosen:** DMs are best-effort live delivery and are not stored in SQLite.

**Rejected:** Persisting every DM body.

**Reason:** V1 durable history is room-based. Keeping DMs live-only avoids storing private message bodies while still demonstrating user-to-user delivery.

---

### Decision 12 — Cache room history but keep SQLite authoritative

**Chosen:** Maintain a bounded, TTL-based in-memory history cache that warms from SQLite on misses and merges pending DB writer messages.

**Rejected:** Treating the cache as the durable source.

**Reason:** The cache improves live history reads, but SQLite remains the source of truth. Pending queued messages are merged so history does not look stale while the writer is draining.

---

### Decision 13 — Enforce handshake before all non-hello messages

**Chosen:** A client must complete `hello -> welcome` before join/chat/history/who/rooms/presence/dm messages are accepted.

**Rejected:** Accepting commands before identity is established.

**Reason:** Room membership and chat attribution require an active nickname and session identity.

---

### Decision 14 — Validate protocol input strictly

**Chosen:** Validate message type, nick format, room format, history limits, body length, UTF-8 frame size, and control characters.

**Rejected:** Letting arbitrary JSON fields flow into handlers.

**Reason:** The network boundary is untrusted. Strict validation prevents malformed protocol states and terminal-control injection in chat bodies.

---

### Decision 15 — Add scheduler-driven maintenance

**Chosen:** A background scheduler drives heartbeats, idle eviction, cache cleanup, history pruning, and stats reporting.

**Rejected:** Running maintenance only during client activity.

**Reason:** Idle clients and expired cache entries must be handled even when no chat messages are flowing.

---

### Decision 16 — Include unsafe demos

**Chosen:** Provide unsafe demonstrations for broken framing, slow-client blocking, room races, blocking DB writes, and shutdown leaks.

**Rejected:** Only showing the safe implementation.

**Reason:** The project is educational. Unsafe demos make the failure modes visible and explain why the safe design exists.

---

## Consequences

**Positive:**
- The protocol is transparent and testable.
- Thread-per-client behavior is easy to reason about.
- Slow clients are isolated by per-client queues.
- One DB writer centralizes SQLite persistence and backpressure.
- Room history survives process restarts.
- Cache improves history reads without owning correctness.
- Handshake, validation, and rate limits protect the protocol boundary.
- Scheduler jobs keep liveness/cleanup behavior independent of chat traffic.
- Admin diagnostics can inspect a live server.
- Unsafe demos strengthen the explanation.

**Negative / Trade-offs:**
- Thread-per-connection has high overhead at large client counts.
- SQLite is a local backend, not a distributed message store.
- The admin socket is localhost-only and unauthenticated, not public-safe.
- DMs are not persisted.
- Public exposure needs auth, TLS, abuse controls, and better account identity.
- Queue overflow policies can drop or disconnect clients depending on configuration.
- JSON Lines is simple but not binary-efficient.

---

## Alternatives Not Explored

- WebSocket protocol.
- HTTP API with polling.
- Selectors or asyncio as the primary V1 engine.
- Redis pub/sub.
- PostgreSQL persistence.
- Account authentication.
- TLS termination.
- End-to-end encryption.
- Persistent direct messages.
- Distributed multi-node rooms.
- Public admin API.

---

*Constitution reference: Article 1 (Python fundamentals and architectural thinking), Article 3.3 (scope discipline), Article 4 (quality proportional to scope), Article 5 (trade-off documentation), Article 6 (verification), and Article 7 (progressive complexity).*

---


# Technical Design Document
## App — Chat Server
**Realtime Messaging Systems Group | Document 2 of 5**

---

## Overview

Chat Server is a reusable Python chat server library plus CLI server and CLI client. It uses raw TCP sockets and JSON Lines framing, implements a threaded server engine, stores room history in SQLite, protects live state with locks, applies bounded backpressure, and exposes a localhost admin control socket for diagnostics and operations.

**Package:** `chat-server-library`  
**Import package:** `chatserver`  
**Python:** `>=3.11`  
**Runtime dependencies:** none  
**CLI commands:** `chatserver`, `chatclient`  
**Implemented engine:** `threaded`  
**Persistence:** SQLite  
**Wire protocol:** UTF-8 JSON object + newline

---

## System Context

```text
chatclient CLI
  │
  ▼
TCP socket
  │
  ▼
ChatServer accept thread
  │
  ├── ClientSession reader thread
  │     ├── recv bytes
  │     ├── FrameDecoder
  │     ├── validate_client_message
  │     └── ChatServer.handle_frame
  │
  ├── ClientSession writer thread
  │     └── bounded outbound queue -> encode_frame -> sendall
  │
  ├── RoomDirectory
  ├── session/nick registries
  ├── HistoryCache
  ├── DbWriter -> SQLiteStore
  ├── PeriodicScheduler
  └── optional AdminServer localhost socket
```

---

## Main Package Areas

```text
src/chatserver/
  __init__.py
  config.py

  protocol/
    framing.py
    validation.py
    messages.py
    errors.py

  network/
    server.py
    session.py
    client.py
    admin.py
    shutdown.py

  engines/
    base.py
    threaded.py

  queues/
    outbound.py
    db_jobs.py
    backpressure.py

  persistence/
    schema.sql
    sqlite_store.py
    writer.py
    migrations.py

  routing/
    rooms.py

  cache/
    history_cache.py

  scheduling/
    scheduler.py

  security/
    rate_limit.py

  observability/
    stats.py
    logging.py
    events.py

  cli/
    main.py
    commands/
```

---

## Wire Protocol

### Framing

Each frame is:

```text
JSON object encoded as UTF-8 + \n
```

The decoder:
- buffers partial TCP reads
- handles multiple frames in one recv
- supports CRLF by trimming trailing `\r`
- rejects oversized frames
- rejects invalid UTF-8
- rejects non-object JSON

### Client message types

Accepted client frame types:
- `hello`
- `join`
- `leave`
- `chat`
- `dm`
- `history`
- `who`
- `rooms`
- `presence`
- `pong`

Handshake rule:
- only `hello` is accepted before welcome/active state

### Server frame builders

Server frames include:
- `welcome`
- `chat`
- `dm`
- `system`
- `history`
- `who`
- `rooms`
- `ping`
- `error`

All server frames are plain dictionaries that flow through cache, queues, and JSON Lines encoding unchanged.

---

## Validation Rules

Nicknames:
```text
^[A-Za-z][A-Za-z0-9_-]{1,31}$
```

Rooms:
```text
^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$
```

Message body:
- 1 to 2,000 characters
- no C0/C1 control characters
- optional UTF-8 byte cap derived from server max frame size

History limit:
- integer from 1 to 200
- server clamps to configured history limit

Pong nonce:
- string up to 128 characters

---

## Server Lifecycle

### Start

```text
ChatServer.start()
  ├── start DbWriter
  ├── create TCP socket
  ├── bind/listen
  ├── register scheduler jobs
  ├── start scheduler thread
  ├── start admin socket if enabled
  ├── start accept thread
  └── set ready event
```

### Scheduler jobs

- heartbeat pings
- idle timeout eviction
- cache cleanup
- history pruning
- stats reporting when enabled

### Stop

```text
ChatServer.stop()
  ├── set stopping flag
  ├── stop admin socket
  ├── close listening socket
  ├── stop/join scheduler
  ├── join accept thread
  ├── send shutdown notice to sessions
  ├── close sessions
  ├── join reader/writer threads
  ├── drain and stop DB writer
  ├── clear registries
  └── update gauges
```

---

## Session Lifecycle

Each `ClientSession` owns:
- socket
- address
- session ID
- user ID
- nickname
- connection state
- frame decoder
- outbound queue
- close event
- session lock
- send lock
- room set
- heartbeat timestamps
- rate limiter
- reader thread
- writer thread

Reader loop:
```text
recv bytes
  ├── update last_seen
  ├── feed FrameDecoder
  ├── send recoverable frame errors
  ├── immediately send fatal frame error and close
  └── dispatch complete frames to ChatServer.handle_frame
```

Writer loop:
```text
while open or outbound queue not empty:
  ├── get queued message
  ├── encode JSON Lines frame
  ├── send under send_lock
  └── apply slow-client policy on timeout/error
```

---

## Chat Message Flow

```text
client sends chat frame
  │
  ▼
reader receives bytes
  │
  ▼
FrameDecoder emits frame
  │
  ▼
validate_client_message
  │
  ▼
rate limiter check
  │
  ▼
room membership check
  │
  ▼
server assigns message_id + timestamp
  │
  ▼
enqueue DB store_message job
  │
  ├── if DB backlog full: reject or disconnect; do not route/cache
  ▼
append to HistoryCache
  │
  ▼
snapshot room members
  │
  ▼
enqueue message to each member's outbound queue
  │
  ▼
recipient writer threads send independently
```

---

## Room Routing

`RoomDirectory` owns:
- room -> session ID set
- RLock

Operations:
- join
- leave
- remove from all rooms
- snapshot members
- room names
- member counts

Broadcast rule:
- snapshot member IDs under room lock
- resolve live sessions under server lock
- release locks
- enqueue to each session

This avoids holding locks across slow-client operations.

---

## Backpressure

### Outbound queue

Every client has a bounded outbound queue.

Policies:
- `disconnect`: evict slow client
- `drop_oldest`: remove oldest queued message, enqueue newest
- `drop_newest`: drop incoming message

### DB writer queue

SQLite writes use a bounded priority queue.

Policies:
- `reject_chat`: return structured `server_busy`; do not route/cache
- `disconnect`: evict sender on DB backlog pressure

DB jobs are priority ordered so room chat persistence is not starved by low-priority audits.

---

## Persistence

SQLite schema:
- `users(nick, first_seen, last_seen)`
- `rooms(name, created_at)`
- `messages(message_id, kind, room, sender, recipient, body, server_timestamp, metadata_json)`
- `events(id, event_type, nick, room, details_json, created_at)`

Indexes:
- room + timestamp for messages
- recipient + timestamp for messages
- event type + created time

Write jobs:
- `store_message`
- `persist_system_message`
- `upsert_user`
- `create_room`
- `record_join`
- `record_leave`
- `record_disconnect`
- `record_eviction`
- `prune_history`
- `prune_events`

`persist_system_message` stores the room/system message and audit row atomically.

---

## History Cache

`HistoryCache` is:
- bounded by max rooms
- bounded by messages per room
- TTL based
- RLock protected
- warmed from SQLite on miss
- marked incomplete after eviction/pruning
- deduplicated by message ID when merging sources

On history request:
- check cache
- on miss, load recent messages from SQLite
- merge DB writer pending room messages
- warm cache
- return limited history frame

SQLite remains authoritative.

---

## Rate Limiting and Liveness

Each session has a sliding-window `RateLimiter`.

Rate limiter:
- max events per window
- injected clock
- lock protected
- rejects over-limit messages with structured error

Liveness:
- scheduler sends ping frames with nonce
- valid pong clears outstanding nonce
- idle eviction uses last seen and last pong timestamps
- handshake timeout evicts clients that connect but never complete hello/welcome

---

## Admin Control Socket

The optional admin server:
- binds only to `127.0.0.1` or `localhost`
- is unauthenticated
- accepts one JSON Lines request per connection
- returns one JSON response
- calls public `ChatServer` API

Commands:
- `stats`
- `clients`
- `rooms`
- `queues`
- `cache`
- `evictions`
- `kick`
- `broadcast`

It is a local operations tool, not a public interface.

---

## Configuration

`ServerConfig` supports TOML or JSON with optional `[server]` section.

Important fields:
- host
- port
- db_path
- engine
- max_connections
- max_message_size
- outbound_queue_size
- outbound_backpressure_policy
- db_queue_size
- db_backpressure_policy
- heartbeat_interval
- idle_timeout
- handshake_timeout
- history_limit
- history_retention_count
- event_retention_count
- room_cache_messages
- max_cached_rooms
- cache_ttl
- rate_limit_messages
- rate_limit_window
- stats_interval
- log_level
- shutdown_timeout
- admin_enabled
- admin_host
- admin_port

Validation rejects:
- unknown keys
- unsupported engine
- invalid backpressure policies
- non-loopback admin host
- non-positive queue/message limits
- invalid port ranges
- history limit larger than room cache messages
- retention count smaller than room cache messages

CLI flags override config file values.

---

## Known Limits

- Thread-per-client model has high overhead at large client counts.
- Only `threaded` engine is implemented.
- Admin socket has no authentication and must remain local.
- No TLS/auth/account model in V1.
- Direct messages are live-only and not persisted.
- SQLite is local-process persistence, not distributed storage.
- Public exposure needs significant hardening.
- Unsafe demos are intentionally broken and should not run in parallel in the same process.

---

## Verification Summary

The repo configures:
- Python 3.11+
- no runtime dependencies
- dev dependencies for pytest, pytest-cov, pytest-timeout, Hypothesis, mypy, Ruff
- strict mypy over `src/chatserver`
- Ruff lint/format checks
- pytest timeout of 120 seconds
- branch coverage over `chatserver`
- GitHub Actions across Python 3.11, 3.12, and 3.13
- CI coverage floor of 65%

README documents a 150+ test suite covering framing, protocol validation, config parsing, rate limiting, cache bounds, cache/scheduler concurrency safety, multi-client chat, rooms, DMs, history, cache warmup, handshake rejection, max connections, idle eviction, disconnect cleanup, history pruning, admin control socket, graceful shutdown/no leaked threads, DB writer behavior, CLI smoke paths, and unsafe teaching demos.

---

*Constitution reference: Article 4 (engineering quality), Article 6 (behavior verification), Article 7 (progressive complexity), and Article 8 (valid learner work).*

---


# Interface Design Specification
## App — Chat Server
**Realtime Messaging Systems Group | Document 3 of 5**

---

## Public CLI Interface

### Server command

```powershell
chatserver <command> [options]
```

Commands:
- `init-db`
- `serve`
- `admin`
- `demo`

Version:

```powershell
chatserver --version
```

---

## `chatserver init-db`

```powershell
chatserver init-db --db chat.db
```

Creates or migrates the SQLite schema.

---

## `chatserver serve`

```powershell
chatserver serve --host 127.0.0.1 --port 9000 --db chat.db
```

With config:

```powershell
chatserver serve --config examples/chatserver.toml
chatserver serve --config examples/chatserver.json
```

Important options:

| Option | Meaning |
|---|---|
| `--host` | Bind host; default localhost |
| `--port` | Bind port |
| `--db` | SQLite DB path |
| `--engine` | Must be `threaded` in V1 |
| `--max-connections` | Connection cap |
| `--max-message-size` | Frame size cap |
| `--outbound-queue-size` | Per-client outbound queue size |
| `--outbound-backpressure-policy` | `disconnect`, `drop_oldest`, `drop_newest` |
| `--db-queue-size` | SQLite writer queue size |
| `--db-backpressure-policy` | `reject_chat`, `disconnect` |
| `--heartbeat-interval` | Ping interval |
| `--idle-timeout` | Idle eviction threshold |
| `--handshake-timeout` | Max time to send hello |
| `--history-limit` | Max returned history messages |
| `--room-cache-messages` | Per-room cache depth |
| `--max-cached-rooms` | Cache room capacity |
| `--cache-ttl` | Cache expiry seconds |
| `--rate-limit-messages` | Per-window message count |
| `--rate-limit-window` | Sliding rate window seconds |
| `--stats-interval` | Stats report interval; 0 disables |
| `--shutdown-timeout` | Join/drain timeout |
| `--admin-port` | Enables localhost admin socket |
| `--admin-host` | Must be loopback |
| `--log-level` | Logging level |

---

## `chatclient connect`

```powershell
chatclient connect --host 127.0.0.1 --port 9000 --nick princeton
```

Version:

```powershell
chatclient --version
```

Interactive commands:

```text
/join <room>
/rooms
/who [room]
/presence [room]
/msg <user> <text>
/history [room] [limit]
/leave <room>
/nick <name>
/help
/quit
```

Plain text without `/` sends a chat frame to the current room. A room becomes current after join is confirmed.

---

## Client Wire Frames

### Hello

```json
{"type":"hello","nick":"princeton"}
```

### Join

```json
{"type":"join","room":"general"}
```

### Leave

```json
{"type":"leave","room":"general"}
```

### Chat

```json
{"type":"chat","room":"general","body":"hello"}
```

### Direct message

```json
{"type":"dm","to":"ada","body":"hello"}
```

### History

```json
{"type":"history","room":"general","limit":25}
```

### Who / Presence

```json
{"type":"who","room":"general"}
{"type":"presence","room":"general"}
```

### Rooms

```json
{"type":"rooms"}
```

### Pong

```json
{"type":"pong","nonce":"p_..."}
```

---

## Server Frames

### Welcome

```json
{"type":"welcome","user_id":"u_...","nick":"princeton"}
```

### Chat

```json
{
  "type":"chat",
  "kind":"chat",
  "message_id":"m_...",
  "room":"general",
  "sender":"princeton",
  "body":"hello",
  "server_timestamp":"...Z",
  "metadata":{"session_id":"s_..."}
}
```

### Direct message

```json
{
  "type":"dm",
  "kind":"dm",
  "message_id":"m_...",
  "sender":"princeton",
  "to":"ada",
  "recipient":"ada",
  "body":"hello",
  "server_timestamp":"...Z",
  "metadata":{"session_id":"s_..."}
}
```

### History

```json
{"type":"history","room":"general","messages":[...]}
```

### Who

```json
{"type":"who","room":"general","users":["ada","princeton"]}
```

### Rooms

```json
{"type":"rooms","rooms":[{"room":"general","members":2}]}
```

### Ping

```json
{"type":"ping","nonce":"p_..."}
```

### Error

```json
{"type":"error","code":"invalid_message","message":"...","recoverable":true}
```

---

## Admin CLI Interface

Live admin requires `chatserver serve --admin-port <port>`.

```powershell
chatserver admin stats     --port 9001
chatserver admin stats     --port 9001 --format table
chatserver admin clients   --port 9001
chatserver admin queues    --port 9001
chatserver admin cache     --port 9001
chatserver admin evictions --port 9001
chatserver admin rooms     --port 9001
chatserver admin kick      --nick ada --port 9001
chatserver admin broadcast --message "restart soon" --port 9001
```

Offline DB commands:

```powershell
chatserver admin stats --db chat.db
chatserver admin rooms --db chat.db
```

Live rooms return member counts. Offline rooms return stored message counts.

---

## Demo Interface

```powershell
chatserver demo framing
chatserver demo basic
chatserver demo multi-client
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

Unsafe demos intentionally run broken patterns and print the failure next to the safe behavior.

---

## Exit Codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Runtime error such as bind failure, DB file missing, admin socket unreachable |
| `2` | Usage/configuration error |
| `130` | Interrupted by Ctrl-C / SIGINT |

---

## Side Effects

| Operation | Side Effect |
|---|---|
| `init-db` | Creates/migrates SQLite schema |
| `serve` | Binds TCP socket and starts threads |
| client connect | Opens TCP connection and sends hello |
| room chat | Enqueues durable DB write, updates cache, routes live message |
| join/leave/rename | Writes audit/system events where possible |
| history | Reads cache and possibly SQLite |
| admin kick | Disconnects a live client |
| admin broadcast | Sends transient system message to active clients |
| scheduler | Sends pings, evicts idle clients, prunes history/events/cache |

---

*Constitution reference: Article 4 (input/output boundaries), Article 6 (verification), and Article 8 (understandable and verifiable work).*

---


# Runbook
## App — Chat Server
**Realtime Messaging Systems Group | Document 4 of 5**

---

## Requirements

### Runtime

- Python 3.11+
- No required third-party runtime dependencies

### Development

- pytest
- pytest-cov
- pytest-timeout
- Hypothesis
- mypy
- Ruff

---

## Installation

### Development install

```powershell
python -m pip install -e ".[dev]"
```

Alternative pinned install:

```powershell
python -m pip install -e . -r requirements-dev.txt
```

---

## First Run

Initialize DB:

```powershell
chatserver init-db --db chat.db
```

Start server:

```powershell
chatserver serve --host 127.0.0.1 --port 9000 --db chat.db
```

Connect a client:

```powershell
chatclient connect --host 127.0.0.1 --port 9000 --nick princeton
```

Inside client:

```text
/join general
hello everyone
/history general 25
/rooms
/who general
/quit
```

---

## Config-Based Run

```powershell
chatserver serve --config examples/chatserver.toml
```

JSON config is also supported:

```powershell
chatserver serve --config examples/chatserver.json
```

CLI flags override config file values.

---

## Admin Socket Run

Start server:

```powershell
chatserver serve --db chat.db --admin-port 9001
```

Inspect stats:

```powershell
chatserver admin stats --port 9001
chatserver admin clients --port 9001
chatserver admin queues --port 9001
chatserver admin cache --port 9001
chatserver admin evictions --port 9001
```

Kick user:

```powershell
chatserver admin kick --nick ada --port 9001
```

Broadcast notice:

```powershell
chatserver admin broadcast --message "restart in 5 minutes" --port 9001
```

---

## Offline DB Diagnostics

```powershell
chatserver admin stats --db chat.db
chatserver admin rooms --db chat.db
```

Use this when the server is not running or admin socket is disabled.

---

## Backpressure Tests

### Slow client policy: disconnect

```powershell
chatserver serve --db chat.db --outbound-queue-size 10 --outbound-backpressure-policy disconnect
```

Expected:
- slow client is evicted
- healthy clients continue receiving messages
- eviction appears in admin evictions/stats

### Drop oldest

```powershell
chatserver serve --db chat.db --outbound-backpressure-policy drop_oldest
```

Expected:
- oldest queued messages are dropped for slow client
- server increments dropped message stats

### DB backlog rejection

```powershell
chatserver serve --db chat.db --db-queue-size 1 --db-backpressure-policy reject_chat
```

Expected:
- server returns `server_busy` when DB queue is full
- rejected chat is not routed or cached

---

## Demo Commands

Run all safe demos:

```powershell
chatserver demo all
```

Run selected demos:

```powershell
chatserver demo framing
chatserver demo basic
chatserver demo multi-client
chatserver demo slow-client
chatserver demo rate-limit
chatserver demo idle-timeout
chatserver demo db-writer
chatserver demo graceful-shutdown
```

Unsafe demos:

```powershell
chatserver demo unsafe-framing
chatserver demo unsafe-slow-client
chatserver demo unsafe-room-race
chatserver demo unsafe-db-blocking
chatserver demo unsafe-shutdown
```

Do not run unsafe demos in parallel in the same process.

---

## Testing

### Full suite

```powershell
python -m pytest
```

### Fast suite

```powershell
python -m pytest -m "not slow"
```

### Coverage

```powershell
python -m pytest --cov --cov-report=term-missing --cov-fail-under=65
```

### Make targets

```powershell
make cov
make check
```

Expected CI checks:
- Ruff lint
- Ruff format check
- mypy strict
- pytest coverage

---

## Health Checks

### Server bind

```powershell
chatserver serve --host 127.0.0.1 --port 0 --db chat.db
```

Expected:
- OS assigns an ephemeral port
- server prints bound host/port

### Admin stats

```powershell
chatserver admin stats --port 9001
```

Expected:
- JSON or table stats
- connected clients, rooms, queue depths, DB writer backlog, cache stats, evictions

### Protocol smoke

Use two clients:

```text
Client A: /join general
Client B: /join general
Client A: hello
Client B: /history general 10
```

Expected:
- Client B receives Client A's message live and/or in history

---

## Troubleshooting

### Port bind fails

Cause:
- port already in use
- permission denied

Fix:
```powershell
chatserver serve --port 0 --db chat.db
```

---

### Client cannot connect

Check:
- server is running
- host/port match
- local firewall
- server printed actual port when `--port 0` was used

---

### Nickname rejected

Rules:
- 2 to 32 chars
- starts with a letter
- letters/numbers/underscore/dash only
- must not already be active

---

### Chat rejected with room error

Cause:
- client has not joined the room
- room name invalid
- current room cleared after leave

Fix:
```text
/join general
```

---

### `server_busy` errors

Cause:
- DB writer queue is full

Actions:
- increase `--db-queue-size`
- inspect `chatserver admin queues`
- reduce incoming chat rate
- check SQLite storage performance

---

### Slow client evicted

Cause:
- outbound queue filled or socket send timed out

Actions:
- increase `--outbound-queue-size`
- inspect client network/read behavior
- choose `drop_oldest` or `drop_newest` if disconnect is too aggressive

---

### History looks stale

Expected behavior:
- cache may warm from SQLite and merge pending writer messages
- after retention prune, cache entries are marked incomplete and reload on next history request

Check:
- DB writer backlog
- history retention settings
- cache stats/warmups

---

### Tests hang locally on Windows

README notes that the full slow socket suite may leave pytest hanging at process exit on Windows because of non-daemon server threads.

Use:

```powershell
python -m pytest -m "not slow"
```

and rely on Ubuntu CI for the full gate.

---

## Maintenance Notes

- Do not hold global locks across socket I/O.
- Preserve JSON Lines frame boundary rules.
- Add tests before changing protocol validation.
- Preserve bounded queues and explicit backpressure policies.
- Keep SQLite writes centralized through `DbWriter`.
- Keep cache non-authoritative.
- Preserve localhost-only admin socket unless authentication is added.
- Keep unsafe demos isolated from production paths.
- Do not claim public-production readiness without auth/TLS/security work.
- Preserve no-runtime-dependency design unless a new ADR justifies the change.

---

*Constitution reference: Article 6 (behavior verification), Article 5 (constraints and trade-offs), and Article 8 (verifiable learner work).*

---


# Lessons Learned
## App — Chat Server
**Realtime Messaging Systems Group | Document 5 of 5**

---

## Why This Design Was Chosen

This design was chosen because chat servers are a direct way to learn networking, concurrency, and backpressure. The simplest visible protocol is raw TCP with JSON Lines framing. It forces the project to handle partial frames, merged frames, invalid UTF-8, oversized inputs, socket closure, and client lifecycle.

Thread-per-connection was selected because it makes the first reliable build understandable. Every client has a reader thread, writer thread, queue, locks, and rate limiter. This costs more resources than selectors or asyncio, but the model is easier to defend and test.

SQLite persistence and the DB writer thread were selected because durability matters, but every client thread writing to SQLite directly would create scattered failure modes. A single writer thread centralizes durability, retry, priority, and backpressure decisions.

---

## What Was Intentionally Omitted

**Authentication/accounts:** Out of scope for V1.

**TLS:** Out of scope; use localhost default only.

**Public deployment hardening:** Out of scope.

**Web UI:** The CLI client/server and admin socket are enough for the networking capstone.

**Selectors/asyncio engines:** Stretch goals behind the same engine interface.

**Persistent DMs:** DMs are live-only by design.

**Distributed rooms:** Single-process local server only.

**Redis/pub-sub:** Deferred until multi-process/multi-node support exists.

---

## Biggest Weakness

The biggest weakness is scalability. Thread-per-connection is simple and reliable for a learning build, but it costs at least two threads per client. At high connection counts, selectors or asyncio would be more efficient.

The second weakness is public safety. The server has protocol validation and rate limits, but it does not have user authentication, authorization, TLS, moderation, durable identity, or abuse prevention.

The third weakness is SQLite as the only durable backend. It is good for local persistence and tests, but not for multi-node chat.

---

## Scaling Considerations

**If client count grows:**
- implement selectors engine
- implement asyncio engine
- reduce per-client thread overhead
- add performance tests for many idle clients

**If public exposure matters:**
- add authentication
- add TLS termination
- add roles/moderation
- secure admin operations
- add abuse detection and rate limits per identity/IP

**If persistence grows:**
- add PostgreSQL backend
- add migrations/versioning beyond schema v1
- add retention controls per room
- separate audit storage from message history

**If distributed chat matters:**
- introduce pub/sub
- add shared presence store
- define message ordering guarantees
- make room membership cross-process

---

## What the Next Refactor Would Be

1. **Selectors engine** — keep protocol and server semantics while replacing per-client reader/writer threads with readiness-based I/O.

2. **Authenticated admin socket** — require a local secret or token for kick/broadcast operations.

3. **Structured protocol versioning** — include protocol version negotiation in hello/welcome.

4. **SQLite migration framework** — make schema upgrades explicit beyond `user_version=1`.

5. **Persistent DM option** — make direct-message persistence opt-in with clear privacy documentation.

---

## What This Project Taught

- **TCP is a stream, not a message bus.** Framing must handle partial and merged reads.

- **Writers need serialization.** Multiple threads writing to one socket can corrupt the byte stream without a send lock.

- **Slow clients are a system problem.** Without bounded queues and eviction/drop policies, one client can harm the whole room.

- **SQLite writes need coordination.** One writer thread makes durability and backpressure easier to reason about.

- **Cache is not truth.** The history cache accelerates reads, but SQLite owns durable history.

- **Locks should protect state, not I/O.** Snapshot state under lock, then release before enqueueing or sending.

- **Unsafe demos are valuable.** They prove the failure modes the safe implementation avoids.

---

*Constitution v2.0 checklist: This document satisfies Article 5 (trade-off documentation), Article 6 (verification), and Article 7 (progressive complexity) for Chat Server.*
