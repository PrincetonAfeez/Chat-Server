CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    room TEXT,
    sender TEXT NOT NULL,
    recipient TEXT,
    body TEXT NOT NULL,
    server_timestamp TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_messages_room_ts ON messages(room, server_timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_recipient_ts ON messages(recipient, server_timestamp);
