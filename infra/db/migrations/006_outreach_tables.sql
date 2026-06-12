-- 006_outreach_tables.sql — Outreach agent: contacts, LinkedIn, sequences

-- ---------------------------------------------------------------------------
-- contacts
-- Unified contact record across all products and channels.
-- Score and tier are updated by the lead_score action.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS contacts (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT        UNIQUE,
    linkedin_url    TEXT        UNIQUE,
    name            TEXT,
    company         TEXT,
    role            TEXT,
    product         TEXT        NOT NULL,
    score           INTEGER     NOT NULL DEFAULT 0,
    tier            TEXT        NOT NULL DEFAULT 'COLD'
                                CHECK (tier IN ('HOT','WARM','COLD')),
    research_notes  TEXT,
    unsubscribed_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS contacts_product_idx  ON contacts (product, created_at DESC);
CREATE INDEX IF NOT EXISTS contacts_score_idx    ON contacts (score DESC);
CREATE INDEX IF NOT EXISTS contacts_tier_idx     ON contacts (tier);
CREATE INDEX IF NOT EXISTS contacts_email_idx    ON contacts (email) WHERE email IS NOT NULL;

-- ---------------------------------------------------------------------------
-- linkedin_outreach
-- One row per LinkedIn action (connect request or DM).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS linkedin_outreach (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id      UUID        NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    action_type     TEXT        NOT NULL CHECK (action_type IN ('connect','message')),
    content_sent    TEXT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    response        TEXT,
    responded_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS linkedin_outreach_contact_idx ON linkedin_outreach (contact_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS linkedin_outreach_type_idx    ON linkedin_outreach (action_type, sent_at DESC);

-- ---------------------------------------------------------------------------
-- outreach_sequences
-- One active sequence per contact. Tracks step progression.
-- Steps (0-indexed): 0=linkedin_connect, 1=linkedin_message, 2=email, 3=followup
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS outreach_sequences (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id      UUID        NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
    product         TEXT        NOT NULL,
    current_step    INTEGER     NOT NULL DEFAULT 0,
    next_action_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT        NOT NULL DEFAULT 'ACTIVE'
                                CHECK (status IN ('ACTIVE','PAUSED','COMPLETE','OPTED_OUT')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contact_id)
);

CREATE INDEX IF NOT EXISTS outreach_sequences_status_idx      ON outreach_sequences (status, next_action_at);
CREATE INDEX IF NOT EXISTS outreach_sequences_next_action_idx ON outreach_sequences (next_action_at) WHERE status = 'ACTIVE';
