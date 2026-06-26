# Concurrency Models
 
The implemented model is thread-per-connection.

Why this model:

- It exposes basic system primitives directly: blocking sockets, threads, locks, queues, shutdown events, and worker joins.
- It is easy to inspect in a debugger.
- It lets the project demonstrate slow-client isolation with per-session writer threads and queues.

Safety rules:

- Shared registries are protected by `RLock`: the session registry, the
  nickname registry, room membership (`RoomDirectory`), the per-room history
  cache (`HistoryCache`), and the stats counters.
- Broadcast uses a snapshot of room members taken under the lock, then releases
  the lock before enqueueing — membership is never mutated while iterating.
- Each session also holds a `send_lock` so the writer thread and any
  `send_immediate` caller (shutdown notice, fatal framing error) can never
  interleave bytes on the same socket.
- A scheduled job that raises is isolated and logged; one failing job never
  kills the scheduler thread (and therefore never stops heartbeats, idle
  eviction, pruning, or cache cleanup).
- DB writes never run in session reader threads.
- Writer threads can block on their own sockets without blocking room routing.

Tradeoffs:

- Many clients mean many threads.
- The design is simpler than selectors or asyncio, but less memory-efficient at high connection counts.
- A future selectors or asyncio engine can share the same protocol, cache, persistence, and CLI layers.
