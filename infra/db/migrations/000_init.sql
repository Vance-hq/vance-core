-- 000_init.sql — Vance shared schema initialisation
-- Runs automatically on first `docker compose up` via postgres initdb.d mount.
-- Safe to re-run: all statements use IF NOT EXISTS.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- uuid_generate_v4()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- fuzzy text search on logs/events
CREATE EXTENSION IF NOT EXISTS "vector";      -- pgvector — memory agent embeddings (requires pgvector/pgvector:pg16 image)

-- ---------------------------------------------------------------------------
-- agent_logs
-- Structured log sink for all agents. Mirrors what shared/logger emits to stdout
-- but persisted for queryable history and alerting.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS agent_logs (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    ts          TIMESTAMPTZ NOT NULL    DEFAULT now(),
    agent       TEXT        NOT NULL,
    level       TEXT        NOT NULL CHECK (level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR')),
    message     TEXT        NOT NULL,
    data        JSONB       NOT NULL    DEFAULT '{}',
    INDEX_ts    BOOLEAN     GENERATED ALWAYS AS (TRUE) STORED  -- placeholder for partial index below
);

-- Drop the dummy column used above (cleaner to add the index directly):
ALTER TABLE agent_logs DROP COLUMN IF EXISTS index_ts;

CREATE INDEX IF NOT EXISTS agent_logs_ts_idx    ON agent_logs (ts DESC);
CREATE INDEX IF NOT EXISTS agent_logs_agent_idx ON agent_logs (agent, ts DESC);
CREATE INDEX IF NOT EXISTS agent_logs_level_idx ON agent_logs (level, ts DESC);

-- ---------------------------------------------------------------------------
-- task_history
-- Long-term persistence of every task that passes through the Redis queue.
-- Schema mirrors shared/types/models.py:Task so records can be reconstructed.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS task_history (
    id              UUID        PRIMARY KEY,          -- same UUID as Redis task id
    agent           TEXT        NOT NULL,             -- AgentCapability value
    action          TEXT        NOT NULL,             -- task.payload.action
    payload         JSONB       NOT NULL DEFAULT '{}',
    priority        SMALLINT    NOT NULL DEFAULT 5,
    status          TEXT        NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','processing','complete','failed','dead')),
    result          JSONB,                            -- TaskResult.output (nullable until complete)
    error           TEXT,                             -- TaskResult.error or exception message
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS task_history_agent_idx  ON task_history (agent, created_at DESC);
CREATE INDEX IF NOT EXISTS task_history_status_idx ON task_history (status, created_at DESC);
CREATE INDEX IF NOT EXISTS task_history_created_idx ON task_history (created_at DESC);

-- ---------------------------------------------------------------------------
-- system_events
-- Agent-emitted events (maps to agents/_base/events.py:EventPayload).
-- Dashboard subscribes to vance:events Redis channel; rows land here async.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS system_events (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    ts          TIMESTAMPTZ NOT NULL    DEFAULT now(),
    event_type  TEXT        NOT NULL,   -- AgentEvent value
    agent       TEXT        NOT NULL,
    task_id     UUID,                   -- FK to task_history (optional, no hard constraint)
    message     TEXT        NOT NULL    DEFAULT '',
    data        JSONB       NOT NULL    DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS system_events_ts_idx         ON system_events (ts DESC);
CREATE INDEX IF NOT EXISTS system_events_agent_idx      ON system_events (agent, ts DESC);
CREATE INDEX IF NOT EXISTS system_events_event_type_idx ON system_events (event_type, ts DESC);
CREATE INDEX IF NOT EXISTS system_events_task_id_idx    ON system_events (task_id) WHERE task_id IS NOT NULL;
