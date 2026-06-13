-- Reporting agent tables
CREATE TABLE IF NOT EXISTS brief_items (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section     TEXT NOT NULL,          -- analytics, sales, security, etc.
    data        JSONB NOT NULL DEFAULT '{}',
    source      TEXT NOT NULL,
    brief_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_brief_items_date ON brief_items (brief_date);

CREATE TABLE IF NOT EXISTS digests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period      TEXT NOT NULL,          -- 'daily' | 'weekly'
    period_date DATE NOT NULL,
    content     TEXT NOT NULL,
    sent_at     TIMESTAMPTZ,
    recipients  JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (period, period_date)
);
