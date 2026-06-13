-- Intel agent tables
CREATE TABLE IF NOT EXISTS intel_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type     TEXT NOT NULL,    -- news | social | pricing | funding
    headline        TEXT NOT NULL,
    source_url      TEXT NOT NULL DEFAULT '',
    product         TEXT NOT NULL DEFAULT '',
    competitor      TEXT NOT NULL DEFAULT '',
    relevance_score INTEGER NOT NULL DEFAULT 5,  -- 1-10
    summary         TEXT NOT NULL DEFAULT '',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_intel_signals_product ON intel_signals (product, detected_at DESC);

CREATE TABLE IF NOT EXISTS keyword_trends (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keyword         TEXT NOT NULL,
    product         TEXT NOT NULL,
    trend_direction TEXT NOT NULL DEFAULT 'stable',  -- rising | falling | stable
    volume_index    INTEGER NOT NULL DEFAULT 0,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (keyword, product)
);
