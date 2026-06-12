-- Scaling agent tables

CREATE TABLE IF NOT EXISTS resource_metrics (
    id          UUID DEFAULT gen_random_uuid(),
    metric_name TEXT NOT NULL,       -- cpu_pct | memory_pct | disk_pct | net_bytes_sent | net_bytes_recv | container_cpu_pct | container_mem_pct
    value       NUMERIC(10, 4) NOT NULL,
    container   TEXT NOT NULL DEFAULT '',  -- empty for host metrics
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- Default partition covering all dates until explicit partitions are created
CREATE TABLE IF NOT EXISTS resource_metrics_default
    PARTITION OF resource_metrics DEFAULT;

CREATE INDEX IF NOT EXISTS idx_resource_metrics_name_at
    ON resource_metrics (metric_name, recorded_at DESC);

CREATE TABLE IF NOT EXISTS scaling_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger     TEXT NOT NULL,       -- high_cpu | high_memory | high_disk | scheduled_plan
    action_taken TEXT NOT NULL,
    outcome     TEXT NOT NULL,       -- success | failed | no_action
    metadata    JSONB NOT NULL DEFAULT '{}',
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scaling_events_occurred ON scaling_events (occurred_at DESC);
