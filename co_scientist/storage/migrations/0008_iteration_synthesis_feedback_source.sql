-- Rename the old system-feedback source into the six-agent vocabulary.
CREATE TABLE IF NOT EXISTS system_feedback (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    source          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    target_id       TEXT,
    text            TEXT NOT NULL,
    artifact_path   TEXT,
    active          INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS fb_sess_active
    ON system_feedback(session_id, active, created_at DESC);

UPDATE system_feedback
   SET source = 'iteration_orchestrator'
 WHERE source = 'meta_' || 'review';
