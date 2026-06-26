# Backpressure

Every client has a bounded outbound queue. Room routing enqueues to recipients
rather than writing directly to sockets, so one slow socket cannot stall delivery
to everyone else.

## Outbound policy (configurable)

`outbound_backpressure_policy` selects what happens when a client's outbound
queue is full:

- `disconnect` (default) — evict the slow client with a `slow_client` error
  frame, then clean up its rooms.
- `drop_oldest` — discard the oldest queued message to make room for the new one.
- `drop_newest` — drop the incoming message and keep the queue as-is.

The policy is validated at startup, exposed in config, and visible in
diagnostics. `drop_oldest`/`drop_newest` increment the `dropped_messages` counter;
`disconnect` increments `slow_client_evictions` and records a recent eviction.

## DB writer policy (configurable)

The DB writer also has a bounded queue. `db_backpressure_policy` selects what
happens when a **room chat** message cannot be enqueued for persistence:

- `reject_chat` (default) — reject the message with a structured `server_busy`
  error before live routing or cache mutation. The client stays connected.
- `disconnect` — evict the offending session after a `server_busy` error frame
  (connection state `DB_BACKLOG`; the wire error code is always `server_busy`).

Under `drop_oldest` / `drop_newest`, the writer may still block on `sendall` when
the peer's TCP receive buffer is full; send timeouts drop the message (and count
as `dropped_messages`) rather than evicting the session.

Direct messages are live-only and are never enqueued. System/join/leave notices
use a composite persistence job; if the DB queue is full the notice is still
broadcast live but is not cached or durably stored until the queue accepts work.
Low-priority audit jobs (`record_join`, etc.) are best-effort under overload;
see `db_jobs_dropped` in live admin stats.

DB jobs are processed highest-`priority`-first (FIFO within a priority band), so
chat persistence is not starved by low-priority audit/system events. Transient
SQLite errors (`OperationalError`) are retried up to three times; permanent
errors are logged and dropped without retry.

## Observable counters

- `slow_client_evictions`, `evicted_clients`, `recent_evictions`
- `dropped_messages`
- `db_writer_backlog`, `db_jobs_enqueued`, `db_jobs_dropped`
- `db_write_successes`, `db_write_failures`
- `rejected_messages`
