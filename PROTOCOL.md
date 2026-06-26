# Chat Protocol

The wire protocol is JSON Lines over UTF-8 on a raw TCP stream.

TCP is a byte stream, not a message protocol. A client or server must never assume that one `recv()` equals one message. Each frame is one JSON object followed by `\n`.

```text
{"type":"hello","nick":"princeton"}\n
```

## Versioning

This first implementation is protocol version `0.1`. The frame format is stable: newline-delimited UTF-8 JSON objects. Future versions should add optional fields rather than changing required field meanings.

## Client To Server

### `hello`

Starts the handshake or renames an active user. On an **already-active** session,
a second `hello` with a new nick performs a rename (rate-limited like other
post-handshake messages). The server responds with another `welcome` frame and
broadcasts a rename system notice to every room the user is in.

```json
{"type":"hello","nick":"princeton"}
```

### `join`

```json
{"type":"join","room":"general"}
```

After a successful join the server automatically sends a `history` frame for
that room (up to `history_limit` messages) before the join system notice.

A duplicate join (already in the room) returns a system notice
`already in {room}` and does not re-broadcast a join event.

### `leave`

```json
{"type":"leave","room":"general"}
```

### `chat`

```json
{"type":"chat","room":"general","body":"hello everyone"}
```

The sender must already be in the target room.

### `dm`

```json
{"type":"dm","to":"ada","body":"private message"}
```

Direct messages are best-effort live delivery only and are **not persisted**;
they are not returned by `history`. The recipient must be connected.

### `history`

```json
{"type":"history","room":"general","limit":25}
```

The client must already be in the target room. When `room` is omitted on the
**wire**, the default is `"general"`. The CLI client (`chatclient`) defaults to
the user's **current room** instead — see client `/help`.

`limit` must be an integer from 1 to 200; the server clamps the effective limit
to `history_limit` from config (default 50).

### `presence`

Alias for `who` — lists connected users globally or in a room. The server
responds with a `who` frame (same shape as the `who` command). Membership in
the target room is **not** required (teaching build).

```json
{"type":"presence","room":"general"}
```

The `room` field is optional.

### `who`

```json
{"type":"who","room":"general"}
```

The `room` field is optional. Without it, the server lists active users.

### `rooms`

```json
{"type":"rooms"}
```

### `pong`

```json
{"type":"pong","nonce":"abc123"}
```

## Server To Client

### `welcome`

```json
{"type":"welcome","user_id":"u_123","nick":"princeton"}
```

### `chat`

```json
{
  "type": "chat",
  "message_id": "m_123",
  "room": "general",
  "sender": "ada",
  "body": "hi",
  "server_timestamp": "2026-06-16T12:00:00Z"
}
```

### `dm`

```json
{
  "type": "dm",
  "message_id": "m_123",
  "sender": "ada",
  "to": "princeton",
  "body": "private",
  "server_timestamp": "2026-06-16T12:00:00Z"
}
```

### `history`

```json
{"type":"history","room":"general","messages":[]}
```

### `who`

```json
{"type":"who","room":"general","users":["ada","princeton"]}
```

### `rooms`

```json
{"type":"rooms","rooms":[{"room":"general","members":2}]}
```

### `system`

```json
{"type":"system","room":"general","body":"ada joined general","server_timestamp":"2026-06-16T12:00:00Z"}
```

### `ping`

```json
{"type":"ping","nonce":"abc123"}
```

### `error`

```json
{"type":"error","code":"bad_json","message":"Malformed JSON frame","recoverable":true}
```

## Server-Added Fields

Server-to-client `chat`, `dm`, and `system` frames may carry extra fields beyond
the examples above. Clients should treat unknown fields as optional and ignore them:

- `message_id` — server-assigned id (also present on persisted system notices)
- `kind` — storage classification (`chat`, `dm`, or `system`)
- `metadata` — server bookkeeping (e.g. originating `session_id`)
- `recipient` — present on `dm` frames alongside `to`

## Validation Rules

- Frames must be valid UTF-8.
- The `max_message_size` cap applies to **client-to-server** frames (bounded
  memory / anti-DoS). Server-to-client frames may be larger when they aggregate
  data — notably a `history` bundle of many messages — so clients use a generous
  inbound buffer rather than the per-message send cap.
- Frames must decode to JSON objects.
- Unknown message types are rejected.
- A client must send `hello` before any room, DM, history, or presence request.
- Nicknames must be 2-32 characters, start with a letter, and use letters, numbers, underscore, or dash.
- Room names must be 1-32 characters and use letters, numbers, underscore, or dash.
- Message bodies must be 1-2000 characters and must not contain control
  characters (C0/C1, including ESC, newline, and tab) — this blocks terminal
  escape-sequence injection into other users' clients. The whole frame must also
  fit within `max_message_size` **bytes**, so for multibyte (non-ASCII) text the
  effective body length can be smaller than 2000 characters.
- Duplicate active nicknames are rejected.
- A connection that never completes the `hello` handshake within
  `handshake_timeout` is dropped (anti-slowloris).

## Error Codes

- `bad_json`
- `frame_too_large`
- `invalid_message`
- `invalid_room`
- `invalid_nick`
- `nick_taken`
- `unauthorized`
- `unknown_command`
- `room_not_found`
- `user_not_found`
- `rate_limited`
- `idle_timeout` — sent before disconnect when the session exceeds `idle_timeout`
- `handshake_timeout` — sent before disconnect when hello is not completed in time
- `kicked` — admin forcibly disconnected the session
- `slow_client` — sent immediately before disconnect when outbound backpressure
  triggers eviction: queue overflow under `disconnect`, or a send timeout under
  `drop_oldest` / `drop_newest`
- `server_shutting_down`
- `server_busy`
- `server_full`
