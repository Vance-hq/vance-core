-- Memory agent — decision log and learned preferences
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS decision_log (
    id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent     TEXT NOT NULL,
    action    TEXT NOT NULL,
    intent    TEXT NOT NULL DEFAULT '',
    outcome   TEXT NOT NULL DEFAULT '',
    product   TEXT NOT NULL DEFAULT '',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    embedding vector(1536)
);

CREATE INDEX IF NOT EXISTS idx_decision_log_product   ON decision_log (product, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_decision_log_agent     ON decision_log (agent, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_decision_log_timestamp ON decision_log (timestamp DESC);
-- Partial index: only rows that actually have an embedding
CREATE INDEX IF NOT EXISTS idx_decision_log_embedding ON decision_log
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
    WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS preferences (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key             TEXT NOT NULL,
    value           TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 0.5,   -- 0.0–1.0
    learned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_evidence TEXT NOT NULL DEFAULT '',
    UNIQUE (key)
);
