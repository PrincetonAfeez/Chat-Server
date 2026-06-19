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

Starts the handshake or renames an active user.

```json
{"type":"hello","nick":"princeton"}
```

### `join`

```json
{"type":"join","room":"general"}
```

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
- Message bodies must be 1-2000 characters.
- Duplicate active nicknames are rejected.

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
- `slow_client`
- `server_shutting_down`
- `server_busy`
- `server_full`
