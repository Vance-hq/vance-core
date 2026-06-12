CREATE TABLE IF NOT EXISTS integration_calls (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service       VARCHAR(64)  NOT NULL,
    method        VARCHAR(128) NOT NULL,
    endpoint      TEXT         NOT NULL DEFAULT '',
    status_code   INTEGER      NOT NULL DEFAULT 0,
    latency_ms    INTEGER      NOT NULL DEFAULT 0,
    task_id       UUID,
    agent         VARCHAR(64)  NOT NULL DEFAULT '',
    called_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    error_msg     TEXT
);

CREATE INDEX IF NOT EXISTS idx_integration_calls_service    ON integration_calls (service);
CREATE INDEX IF NOT EXISTS idx_integration_calls_called_at  ON integration_calls (called_at DESC);
CREATE INDEX IF NOT EXISTS idx_integration_calls_task_id    ON integration_calls (task_id) WHERE task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_integration_calls_status     ON integration_calls (status_code) WHERE status_code >= 400;
