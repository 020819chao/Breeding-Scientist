CREATE TABLE IF NOT EXISTS agent_output_reviews (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    agent           TEXT NOT NULL,
    output_key      TEXT NOT NULL,
    output_path     TEXT,
    target_id       TEXT,
    status          TEXT NOT NULL,
    reviewer        TEXT NOT NULL,
    note            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS agent_output_review_sess
    ON agent_output_reviews(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS agent_output_review_key
    ON agent_output_reviews(session_id, output_key, created_at DESC);
