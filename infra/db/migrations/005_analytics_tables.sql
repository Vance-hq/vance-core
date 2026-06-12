-- Time-series metric store — one row per measured value per snapshot cycle.
CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_type  VARCHAR(64)  NOT NULL,
    metric_value NUMERIC(18,4) NOT NULL,
    metadata     JSONB        NOT NULL DEFAULT '{}',
    period_start TIMESTAMPTZ,
    period_end   TIMESTAMPTZ,
    source       VARCHAR(32)  NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_type    ON analytics_snapshots (metric_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_source  ON analytics_snapshots (source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_created ON analytics_snapshots (created_at DESC);

-- Cached LLM-generated reports.
CREATE TABLE IF NOT EXISTS analytics_reports (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type  VARCHAR(64) NOT NULL,
    content      JSONB       NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_analytics_reports_type ON analytics_reports (report_type, generated_at DESC);

-- Anomaly log — records every detected deviation.
CREATE TABLE IF NOT EXISTS analytics_anomalies (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_type  VARCHAR(64)  NOT NULL,
    current_val  NUMERIC(18,4) NOT NULL,
    baseline_val NUMERIC(18,4) NOT NULL,
    change_pct   NUMERIC(8,4) NOT NULL,
    alerted      BOOLEAN      NOT NULL DEFAULT FALSE,
    detected_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_anomalies_detected ON analytics_anomalies (detected_at DESC);
