-- Migration 026: reporting tables
-- reports: stores generated daily briefs, weekly summaries, and on-demand reports
-- alerts_log: audit log of every alert delivered, with delivery + acknowledgement timestamps

CREATE TABLE IF NOT EXISTS reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type TEXT NOT NULL,                   -- daily_brief | weekly_summary | on_demand
    product     TEXT,                            -- null = cross-product
    period_date DATE NOT NULL,
    content_text TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_reports_type_date ON reports (report_type, period_date DESC);
CREATE INDEX IF NOT EXISTS idx_reports_product   ON reports (product) WHERE product IS NOT NULL;

CREATE TABLE IF NOT EXISTS alerts_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_agent    TEXT NOT NULL,
    alert_type      TEXT NOT NULL,               -- production_down | mrr_drop | security_incident | p0_bug | general
    message         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at    TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alerts_log_type        ON alerts_log (alert_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_log_undelivered ON alerts_log (delivered_at) WHERE delivered_at IS NULL;
