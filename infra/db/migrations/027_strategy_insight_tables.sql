-- Migration 027: strategy insight tables
-- strategy_insights: daily cross-product synthesis results
-- recommendations: agent-generated action recommendations with auto-execute tracking
-- pivot_alerts: product strategy failure detections awaiting Dutch's review

CREATE TABLE IF NOT EXISTS strategy_insights (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    insight           TEXT NOT NULL,
    products_affected JSONB NOT NULL DEFAULT '[]',
    confidence        FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    actioned          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_insights_created ON strategy_insights (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_insights_actioned ON strategy_insights (actioned) WHERE actioned = FALSE;

CREATE TABLE IF NOT EXISTS recommendations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation TEXT NOT NULL,
    rationale      TEXT NOT NULL,
    agent_target   TEXT NOT NULL,
    confidence     FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    executed       BOOLEAN NOT NULL DEFAULT FALSE,
    outcome        TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recommendations_created   ON recommendations (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recommendations_unexecuted ON recommendations (executed) WHERE executed = FALSE;

CREATE TABLE IF NOT EXISTS pivot_alerts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product            TEXT NOT NULL,
    diagnosis          TEXT NOT NULL,
    options            JSONB NOT NULL DEFAULT '[]',
    recommended_option TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',   -- pending | actioned | dismissed
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pivot_alerts_product ON pivot_alerts (product, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pivot_alerts_pending ON pivot_alerts (status) WHERE status = 'pending';
