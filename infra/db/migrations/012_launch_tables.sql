-- 012_launch_tables.sql — Launch agent: launch_plans, launch_results

-- ---------------------------------------------------------------------------
-- launch_plans
-- One row per launch. tasks is a JSONB array of task objects.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS launch_plans (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product     TEXT        NOT NULL,
    launch_type TEXT        NOT NULL
                CHECK (launch_type IN ('new_product','major_feature','price_change','rebrand')),
    launch_date DATE        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'planned'
                CHECK (status IN ('planned','in_progress','completed','aborted')),
    tasks       JSONB       NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS launch_plans_product_idx ON launch_plans (product, launch_date DESC);
CREATE INDEX IF NOT EXISTS launch_plans_status_idx  ON launch_plans (status) WHERE status IN ('planned','in_progress');
CREATE INDEX IF NOT EXISTS launch_plans_date_idx    ON launch_plans (launch_date);

-- ---------------------------------------------------------------------------
-- launch_results
-- Immutable metric snapshots captured at T+7 debrief.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS launch_results (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    launch_id   UUID        NOT NULL REFERENCES launch_plans (id) ON DELETE CASCADE,
    metric      TEXT        NOT NULL,
    value       TEXT        NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS launch_results_launch_idx  ON launch_results (launch_id);
CREATE INDEX IF NOT EXISTS launch_results_metric_idx  ON launch_results (metric, recorded_at DESC);
