-- 011_research_tables.sql — Research agent: competitor_snapshots, market_signals, feature_gaps, sentiment_reports

-- ---------------------------------------------------------------------------
-- competitor_snapshots
-- One row per (product, competitor, scan). Immutable — append only.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS competitor_snapshots (
    id               UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product          TEXT        NOT NULL,
    competitor       TEXT        NOT NULL,
    snapshot_date    DATE        NOT NULL DEFAULT CURRENT_DATE,
    changes_detected BOOLEAN     NOT NULL DEFAULT FALSE,
    summary          TEXT        NOT NULL DEFAULT '',
    raw_content      TEXT        NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS competitor_snapshots_product_idx    ON competitor_snapshots (product, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS competitor_snapshots_competitor_idx ON competitor_snapshots (competitor, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS competitor_snapshots_changes_idx    ON competitor_snapshots (product, changes_detected) WHERE changes_detected = TRUE;

-- ---------------------------------------------------------------------------
-- market_signals
-- Industry signals scored by LLM relevance.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS market_signals (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product         TEXT        NOT NULL,
    source          TEXT        NOT NULL,
    headline        TEXT        NOT NULL,
    url             TEXT        NOT NULL DEFAULT '',
    relevance_score SMALLINT    NOT NULL CHECK (relevance_score BETWEEN 0 AND 10),
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    actioned        BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS market_signals_product_idx    ON market_signals (product, detected_at DESC);
CREATE INDEX IF NOT EXISTS market_signals_relevance_idx  ON market_signals (product, relevance_score DESC);
CREATE INDEX IF NOT EXISTS market_signals_actioned_idx   ON market_signals (actioned) WHERE actioned = FALSE;

-- ---------------------------------------------------------------------------
-- feature_gaps
-- Unique per (product, feature). Upserted on each quarterly run.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS feature_gaps (
    id                    UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product               TEXT        NOT NULL,
    feature               TEXT        NOT NULL,
    competitor_coverage   INTEGER     NOT NULL DEFAULT 0,
    customer_demand_score INTEGER     NOT NULL DEFAULT 0,
    status                TEXT        NOT NULL DEFAULT 'proposed'
                          CHECK (status IN ('proposed', 'in_progress', 'shipped', 'declined')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product, feature)
);

CREATE INDEX IF NOT EXISTS feature_gaps_product_idx ON feature_gaps (product, customer_demand_score DESC);
CREATE INDEX IF NOT EXISTS feature_gaps_status_idx  ON feature_gaps (product, status);

-- ---------------------------------------------------------------------------
-- sentiment_reports
-- Monthly batch sentiment output per product.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sentiment_reports (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product     TEXT        NOT NULL,
    report_data JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sentiment_reports_product_idx ON sentiment_reports (product, created_at DESC);
