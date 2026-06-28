CREATE INDEX IF NOT EXISTS idx_messages_room_ts ON messages(room, server_timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_recipient_ts ON messages(recipient, server_timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, created_at);
