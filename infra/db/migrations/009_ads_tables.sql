-- 009_ads_tables.sql — Ads agent: campaigns, performance, creative tests, budget log

CREATE TABLE IF NOT EXISTS ad_campaigns (
    id                          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product                     TEXT        NOT NULL,
    platform                    TEXT        NOT NULL CHECK (platform IN ('google','meta')),
    name                        TEXT        NOT NULL,
    objective                   TEXT        NOT NULL DEFAULT '',
    status                      TEXT        NOT NULL DEFAULT 'active'
                                            CHECK (status IN ('active','paused','archived')),
    budget_daily                NUMERIC(10,2) NOT NULL,
    platform_campaign_id        TEXT,
    platform_ad_set_id          TEXT,
    platform_budget_resource    TEXT,
    target_cpa                  NUMERIC(10,2),
    target_roas                 NUMERIC(6,2),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    paused_at                   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ad_campaigns_product_idx  ON ad_campaigns (product, status);
CREATE INDEX IF NOT EXISTS ad_campaigns_platform_idx ON ad_campaigns (platform, status);

-- ---------------------------------------------------------------------------
-- ad_performance
-- One row per campaign per day. UNIQUE prevents double-writes.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ad_performance (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     UUID        NOT NULL REFERENCES ad_campaigns (id) ON DELETE CASCADE,
    date            DATE        NOT NULL,
    spend           NUMERIC(10,2) NOT NULL DEFAULT 0,
    impressions     INTEGER     NOT NULL DEFAULT 0,
    clicks          INTEGER     NOT NULL DEFAULT 0,
    conversions     NUMERIC(8,2) NOT NULL DEFAULT 0,
    cpa             NUMERIC(10,2),
    roas            NUMERIC(8,2),
    ctr             NUMERIC(6,4),
    frequency       NUMERIC(6,2),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (campaign_id, date)
);

CREATE INDEX IF NOT EXISTS ad_performance_campaign_date_idx ON ad_performance (campaign_id, date DESC);

-- ---------------------------------------------------------------------------
-- creative_tests
-- A/B test between two creative variants (text only; image refs stored as text).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS creative_tests (
    id                  UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id         UUID    NOT NULL REFERENCES ad_campaigns (id) ON DELETE CASCADE,
    variant_a           TEXT    NOT NULL,
    variant_b           TEXT    NOT NULL,
    variant_a_platform_id TEXT,
    variant_b_platform_id TEXT,
    impressions_a       INTEGER NOT NULL DEFAULT 0,
    impressions_b       INTEGER NOT NULL DEFAULT 0,
    clicks_a            INTEGER NOT NULL DEFAULT 0,
    clicks_b            INTEGER NOT NULL DEFAULT 0,
    winner              TEXT    CHECK (winner IN ('a','b')),
    status              TEXT    NOT NULL DEFAULT 'running'
                                CHECK (status IN ('running','complete','cancelled')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS creative_tests_campaign_idx ON creative_tests (campaign_id, status);

-- ---------------------------------------------------------------------------
-- ad_budget_log
-- Immutable audit trail of every budget change.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ad_budget_log (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID        NOT NULL REFERENCES ad_campaigns (id) ON DELETE CASCADE,
    old_budget  NUMERIC(10,2) NOT NULL,
    new_budget  NUMERIC(10,2) NOT NULL,
    reason      TEXT        NOT NULL,
    changed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ad_budget_log_campaign_idx ON ad_budget_log (campaign_id, changed_at DESC);
