# Backpressure

Every client has a bounded outbound queue. Room routing enqueues to recipients
rather than writing directly to sockets, so one slow socket cannot stall delivery
to everyone else.

## Outbound policy (configurable)

`outbound_backpressure_policy` selects what happens when a client's outbound
queue is full:

- `disconnect` (default) — evict the slow client and clean up its rooms.
- `drop_oldest` — discard the oldest queued message to make room for the new one.
- `drop_newest` — drop the incoming message and keep the queue as-is.

The policy is validated at startup, exposed in config, and visible in
diagnostics. `drop_oldest`/`drop_newest` increment the `dropped_messages` counter;
`disconnect` increments `slow_client_evictions` and records a recent eviction.

## DB writer policy (configurable)

The DB writer also has a bounded queue. `db_backpressure_policy` selects what
happens when a chat/DM cannot be enqueued:

- `reject_chat` (default) — reject the message with a structured `server_busy`
  error before live routing or cache mutation.
- `disconnect` — evict the offending session.

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
