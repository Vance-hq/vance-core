-- 003_grader_tables.sql — LocalRankGrader audit engine schema

-- ---------------------------------------------------------------------------
-- grader_audits
-- One row per GBP audit. category_scores and recommendations stored as JSONB.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS grader_audits (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_name       TEXT        NOT NULL,
    place_id            TEXT,
    address             TEXT,
    contact_email       TEXT        NOT NULL,
    contact_name        TEXT,
    overall_score       INTEGER     NOT NULL DEFAULT 0
                        CHECK (overall_score BETWEEN 0 AND 100),
    category_scores     JSONB       NOT NULL DEFAULT '{}',
    recommendations     JSONB       NOT NULL DEFAULT '[]',
    raw_places_data     JSONB       NOT NULL DEFAULT '{}',
    report_url          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS grader_audits_email_idx      ON grader_audits (contact_email);
CREATE INDEX IF NOT EXISTS grader_audits_place_id_idx   ON grader_audits (place_id) WHERE place_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS grader_audits_created_at_idx ON grader_audits (created_at DESC);
CREATE INDEX IF NOT EXISTS grader_audits_score_idx      ON grader_audits (overall_score);

-- ---------------------------------------------------------------------------
-- grader_leads
-- One row per lead generated from an audit submission.
-- score drives upgrade_nudge dispatch (>= 80 → sales agent).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS grader_leads (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    audit_id            UUID        NOT NULL REFERENCES grader_audits (id) ON DELETE CASCADE,
    email               TEXT        NOT NULL,
    contact_name        TEXT,
    product_interest    TEXT        NOT NULL DEFAULT 'local_rank_grader',
    score               INTEGER     NOT NULL DEFAULT 0,
    sequence_step       INTEGER     NOT NULL DEFAULT 1,
    trial_started_at    TIMESTAMPTZ,
    converted_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS grader_leads_audit_email_idx ON grader_leads (audit_id, email);
CREATE INDEX IF NOT EXISTS grader_leads_email_idx              ON grader_leads (email);
CREATE INDEX IF NOT EXISTS grader_leads_score_idx              ON grader_leads (score DESC);
CREATE INDEX IF NOT EXISTS grader_leads_sequence_step_idx      ON grader_leads (sequence_step);

-- ---------------------------------------------------------------------------
-- grader_benchmarks
-- Lightweight competitor audits added to each report for social proof.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS grader_benchmarks (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    audit_id            UUID        NOT NULL REFERENCES grader_audits (id) ON DELETE CASCADE,
    competitor_name     TEXT        NOT NULL,
    competitor_place_id TEXT,
    competitor_score    INTEGER     NOT NULL DEFAULT 0
                        CHECK (competitor_score BETWEEN 0 AND 100),
    competitor_address  TEXT,
    category_scores     JSONB       NOT NULL DEFAULT '{}',
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS grader_benchmarks_audit_idx ON grader_benchmarks (audit_id);

-- ---------------------------------------------------------------------------
-- grader_email_events
-- Open and click events for nurture sequence tracking.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS grader_email_events (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    lead_id     UUID        NOT NULL REFERENCES grader_leads (id) ON DELETE CASCADE,
    event_type  TEXT        NOT NULL CHECK (event_type IN ('open', 'click', 'pricing_visit')),
    sequence_step INTEGER,
    score_delta INTEGER     NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS grader_email_events_lead_idx  ON grader_email_events (lead_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS grader_email_events_type_idx  ON grader_email_events (event_type, recorded_at DESC);
