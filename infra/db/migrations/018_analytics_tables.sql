-- Analytics agent tables
-- usage snapshots per product/day
CREATE TABLE IF NOT EXISTS usage_snapshots (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product     TEXT NOT NULL,
    date        DATE NOT NULL,
    metrics     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product, date)
);

-- funnel step snapshots per product/date/step
CREATE TABLE IF NOT EXISTS funnel_snapshots (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product                     TEXT NOT NULL,
    date                        DATE NOT NULL,
    step                        TEXT NOT NULL,
    count                       INTEGER NOT NULL DEFAULT 0,
    conversion_rate_from_prev   NUMERIC(6,4),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_funnel_snapshots_product_date ON funnel_snapshots (product, date);

-- monthly cohort retention
CREATE TABLE IF NOT EXISTS cohort_data (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product             TEXT NOT NULL,
    cohort_month        TEXT NOT NULL,   -- 'YYYY-MM'
    day_30_retention    NUMERIC(5,4),
    day_60_retention    NUMERIC(5,4),
    day_90_retention    NUMERIC(5,4),
    cohort_size         INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product, cohort_month)
);

-- per-feature weekly usage
CREATE TABLE IF NOT EXISTS feature_usage (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product         TEXT NOT NULL,
    feature_name    TEXT NOT NULL,
    week            TEXT NOT NULL,      -- 'YYYY-WNN'
    unique_users    INTEGER NOT NULL DEFAULT 0,
    total_events    INTEGER NOT NULL DEFAULT 0,
    adoption_pct    NUMERIC(5,4),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product, feature_name, week)
);

-- per-user engagement scores
CREATE TABLE IF NOT EXISTS engagement_scores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL,
    product         TEXT NOT NULL,
    score           NUMERIC(6,3) NOT NULL DEFAULT 0,
    tier            TEXT NOT NULL DEFAULT 'ACTIVE',  -- POWER_USER|ACTIVE|AT_RISK|DORMANT
    calculated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, product)
);
CREATE INDEX IF NOT EXISTS idx_engagement_scores_product_tier ON engagement_scores (product, tier);

-- A/B test registry
CREATE TABLE IF NOT EXISTS ab_tests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent           TEXT NOT NULL,
    product         TEXT NOT NULL,
    test_name       TEXT NOT NULL,
    variant_a       TEXT NOT NULL,
    variant_b       TEXT NOT NULL,
    metric          TEXT NOT NULL,
    sample_size_a   INTEGER NOT NULL DEFAULT 0,
    sample_size_b   INTEGER NOT NULL DEFAULT 0,
    conversions_a   INTEGER NOT NULL DEFAULT 0,
    conversions_b   INTEGER NOT NULL DEFAULT 0,
    p_value         NUMERIC(8,6),
    winner          TEXT,
    status          TEXT NOT NULL DEFAULT 'running',    -- running|significant|concluded
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent, product, test_name)
);
