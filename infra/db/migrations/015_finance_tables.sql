-- Finance agent tables

CREATE TABLE IF NOT EXISTS mrr_snapshots (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date DATE NOT NULL,
    product     TEXT NOT NULL DEFAULT 'default',
    mrr_cents   BIGINT NOT NULL,
    arr_cents   BIGINT NOT NULL,
    subscriber_count INTEGER NOT NULL DEFAULT 0,
    new_mrr_cents    BIGINT NOT NULL DEFAULT 0,
    churned_mrr_cents BIGINT NOT NULL DEFAULT 0,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_date, product)
);

CREATE TABLE IF NOT EXISTS cost_snapshots (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period_month DATE NOT NULL,        -- first day of month
    vendor      TEXT NOT NULL,         -- contabo | anthropic | vercel | other
    cost_cents  BIGINT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'infrastructure',
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (period_month, vendor)
);

CREATE TABLE IF NOT EXISTS unit_economics (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period_month    DATE NOT NULL UNIQUE,
    cac_cents       BIGINT NOT NULL DEFAULT 0,
    ltv_cents       BIGINT NOT NULL DEFAULT 0,
    ltv_cac_ratio   NUMERIC(8, 2) NOT NULL DEFAULT 0,
    payback_months  NUMERIC(8, 2) NOT NULL DEFAULT 0,
    new_customers   INTEGER NOT NULL DEFAULT 0,
    sales_marketing_spend_cents BIGINT NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mrr_snapshots_date ON mrr_snapshots (snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_cost_snapshots_month ON cost_snapshots (period_month DESC);
