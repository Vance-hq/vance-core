-- Strategy agent tables
CREATE TABLE IF NOT EXISTS strategic_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product         TEXT NOT NULL,
    quarter         TEXT NOT NULL,    -- e.g. '2026-Q3'
    okrs            JSONB NOT NULL DEFAULT '[]',
    growth_levers   JSONB NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'draft',  -- draft | active | reviewed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (product, quarter)
);

CREATE TABLE IF NOT EXISTS strategy_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product         TEXT NOT NULL,
    signal_type     TEXT NOT NULL,    -- competitor | retention | feature | pricing
    summary         TEXT NOT NULL,
    recommendation  TEXT NOT NULL DEFAULT '',
    source_agent    TEXT NOT NULL,
    actioned        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
