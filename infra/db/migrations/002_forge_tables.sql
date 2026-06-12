-- 002_forge_tables.sql — Forge cold outreach engine schema
-- Mirrors the Forge repo DB. Runs automatically after 001_webhook_tables.sql.

-- ---------------------------------------------------------------------------
-- forge_leads
-- One row per prospected contact. Enriched incrementally as data arrives.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS forge_leads (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product         TEXT        NOT NULL,
    email           TEXT        UNIQUE,
    first_name      TEXT,
    last_name       TEXT,
    company         TEXT,
    title           TEXT,
    city            TEXT,
    phone           TEXT,
    website         TEXT,
    score           INTEGER     NOT NULL DEFAULT 0,
    status          TEXT        NOT NULL DEFAULT 'NEW'
                    CHECK (status IN ('NEW','CONTACTED','HOT','COLD','CONVERTED','UNSUBSCRIBED','BOUNCED')),
    crm_id          TEXT,           -- Twenty CRM person ID
    research_notes  TEXT,
    source          TEXT,           -- 'google_maps' | 'linkedin' | 'apollo' | 'hunter' | 'searxng'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS forge_leads_product_idx  ON forge_leads (product, created_at DESC);
CREATE INDEX IF NOT EXISTS forge_leads_status_idx   ON forge_leads (status);
CREATE INDEX IF NOT EXISTS forge_leads_score_idx    ON forge_leads (score DESC);
CREATE INDEX IF NOT EXISTS forge_leads_email_idx    ON forge_leads (email) WHERE email IS NOT NULL;

-- ---------------------------------------------------------------------------
-- forge_sequences
-- Outreach sequence templates. steps JSONB is an ordered array:
-- [{"step": 1, "delay_days": 0, "subject": "...", "body_html": "...", "body_text": "..."}]
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS forge_sequences (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    product         TEXT        NOT NULL,
    name            TEXT        NOT NULL,
    steps           JSONB       NOT NULL DEFAULT '[]',
    status          TEXT        NOT NULL DEFAULT 'DRAFT'
                    CHECK (status IN ('DRAFT','ACTIVE','PAUSED','COMPLETE')),
    active_variant  JSONB       NOT NULL DEFAULT '{}',   -- winning A/B variant overrides
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS forge_sequences_product_idx ON forge_sequences (product);
CREATE INDEX IF NOT EXISTS forge_sequences_status_idx  ON forge_sequences (status);

-- ---------------------------------------------------------------------------
-- forge_sends
-- One row per email sent. message_id links to Mailcow reply threading.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS forge_sends (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    lead_id         UUID        NOT NULL REFERENCES forge_leads (id) ON DELETE CASCADE,
    sequence_id     UUID        NOT NULL REFERENCES forge_sequences (id) ON DELETE CASCADE,
    step_number     INTEGER     NOT NULL,
    subject         TEXT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_alias      TEXT        NOT NULL,
    message_id      TEXT        UNIQUE,         -- SMTP Message-ID header for reply threading
    status          TEXT        NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING','SENT','DELIVERED','BOUNCED','FAILED'))
);

CREATE INDEX IF NOT EXISTS forge_sends_lead_idx     ON forge_sends (lead_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS forge_sends_sequence_idx ON forge_sends (sequence_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS forge_sends_status_idx   ON forge_sends (status);
CREATE INDEX IF NOT EXISTS forge_sends_sent_at_idx  ON forge_sends (sent_at DESC);

-- ---------------------------------------------------------------------------
-- forge_opens
-- Pixel tracking hits. One row per open event (can be multiple per send).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS forge_opens (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    send_id     UUID        NOT NULL REFERENCES forge_sends (id) ON DELETE CASCADE,
    opened_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_address  TEXT
);

CREATE INDEX IF NOT EXISTS forge_opens_send_idx    ON forge_opens (send_id);
CREATE INDEX IF NOT EXISTS forge_opens_time_idx    ON forge_opens (opened_at DESC);

-- ---------------------------------------------------------------------------
-- forge_replies
-- Reply classification from Mailcow Sieve → webhook → LLM classifier.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS forge_replies (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    send_id     UUID        REFERENCES forge_sends (id) ON DELETE SET NULL,
    reply_type  TEXT        NOT NULL
                CHECK (reply_type IN ('INTERESTED','NOT_INTERESTED','UNSUBSCRIBE',
                                      'OUT_OF_OFFICE','QUESTION','BOUNCE')),
    reply_body  TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS forge_replies_send_idx  ON forge_replies (send_id) WHERE send_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS forge_replies_type_idx  ON forge_replies (reply_type, received_at DESC);

-- ---------------------------------------------------------------------------
-- forge_ab_tests
-- A/B test results per sequence. winner = NULL while test is running.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS forge_ab_tests (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    sequence_id     UUID        NOT NULL REFERENCES forge_sequences (id) ON DELETE CASCADE,
    variant_a       JSONB       NOT NULL,   -- {"field": "subject", "value": "..."}
    variant_b       JSONB       NOT NULL,
    metric          TEXT        NOT NULL    CHECK (metric IN ('open_rate','reply_rate')),
    winner          TEXT                    CHECK (winner IN ('A','B')),
    confidence      NUMERIC(5,4),           -- 0.0000–1.0000
    analysis        TEXT,                   -- LLM reasoning
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS forge_ab_tests_sequence_idx ON forge_ab_tests (sequence_id, created_at DESC);
