-- 014_deploy_tables.sql — Deploy agent: pipeline_runs + ensures deployments/build_log exist

-- ---------------------------------------------------------------------------
-- deployments (shared with dev agent — created here if not yet present)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS deployments (
    id                   UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo                 TEXT        NOT NULL,
    environment          TEXT        NOT NULL DEFAULT 'production',
    version              TEXT        NOT NULL,
    status               TEXT        NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','success','failed','rolled_back')),
    deployed_by_task_id  TEXT,
    deployed_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS deployments_repo_env_idx ON deployments (repo, environment, deployed_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS deployments_status_idx   ON deployments (status) WHERE status IN ('pending','success');

-- ---------------------------------------------------------------------------
-- build_log (shared with dev agent)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS build_log (
    id               UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo             TEXT        NOT NULL,
    task_type        TEXT        NOT NULL,
    issue_number     INTEGER,
    success          BOOLEAN     NOT NULL,
    duration_seconds NUMERIC(10,2),
    error_msg        TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS build_log_repo_idx ON build_log (repo, created_at DESC);

-- ---------------------------------------------------------------------------
-- pipeline_runs
-- One row per CI run triggered by a PR event.
-- steps is a JSONB array: [{name, success, output, duration_ms}]
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo         TEXT        NOT NULL,
    pr_number    INTEGER,
    branch       TEXT,
    build_id     TEXT,
    status       TEXT        NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','success','failed','cancelled')),
    steps        JSONB       NOT NULL DEFAULT '[]',
    duration_ms  INTEGER,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS pipeline_runs_repo_pr_idx  ON pipeline_runs (repo, pr_number, triggered_at DESC);
CREATE INDEX IF NOT EXISTS pipeline_runs_build_id_idx ON pipeline_runs (build_id) WHERE build_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS pipeline_runs_status_idx   ON pipeline_runs (status, triggered_at DESC);
