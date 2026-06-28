CREATE TABLE IF NOT EXISTS users (
    nick TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
