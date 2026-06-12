-- 001_webhook_tables.sql — Tables for the webhook service
-- Runs automatically on first docker compose up (alphabetical order after 000_init.sql).

-- ---------------------------------------------------------------------------
-- contacts
-- Central contact record used by marketing and outreach agents.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS contacts (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT        NOT NULL UNIQUE,
    name            TEXT,
    company         TEXT,
    source          TEXT,                       -- e.g. "campaign", "manual", "import"
    unsubscribed    BOOLEAN     NOT NULL DEFAULT FALSE,
    unsubscribed_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS contacts_email_idx       ON contacts (email);
CREATE INDEX IF NOT EXISTS contacts_unsubscribed_idx ON contacts (unsubscribed) WHERE unsubscribed = TRUE;

-- ---------------------------------------------------------------------------
-- campaign_sends
-- One row per email sent in a campaign. The webhook handler looks up a send
-- by message_id to get campaign context when a reply arrives.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS campaign_sends (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    message_id      TEXT        NOT NULL UNIQUE,    -- SMTP Message-ID header
    campaign_id     TEXT        NOT NULL,
    campaign_name   TEXT,
    contact_id      UUID        REFERENCES contacts (id) ON DELETE SET NULL,
    contact_email   TEXT        NOT NULL,
    contact_name    TEXT,
    subject         TEXT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    agent           TEXT        NOT NULL DEFAULT 'outreach'
);

CREATE INDEX IF NOT EXISTS campaign_sends_message_id_idx  ON campaign_sends (message_id);
CREATE INDEX IF NOT EXISTS campaign_sends_campaign_id_idx ON campaign_sends (campaign_id);
CREATE INDEX IF NOT EXISTS campaign_sends_contact_id_idx  ON campaign_sends (contact_id);

-- ---------------------------------------------------------------------------
-- reply_classifications
-- Log of every Mailcow reply that was classified by the webhook handler.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reply_classifications (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    classified_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    reply_message_id    TEXT        NOT NULL,       -- Message-ID of the reply
    original_message_id TEXT,                       -- In-Reply-To header
    from_email          TEXT        NOT NULL,
    to_email            TEXT        NOT NULL,
    subject             TEXT,
    category            TEXT        NOT NULL
                        CHECK (category IN ('INTERESTED','NOT_INTERESTED','UNSUBSCRIBE','OUT_OF_OFFICE','QUESTION')),
    confidence          NUMERIC(4,3),               -- 0.000 – 1.000
    classified_by       TEXT        NOT NULL DEFAULT 'llm',  -- 'llm' | 'keyword'
    task_id             UUID,                       -- Redis task id if enqueued
    send_id             UUID        REFERENCES campaign_sends (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS reply_class_from_idx       ON reply_classifications (from_email, classified_at DESC);
CREATE INDEX IF NOT EXISTS reply_class_category_idx   ON reply_classifications (category, classified_at DESC);
CREATE INDEX IF NOT EXISTS reply_class_send_id_idx    ON reply_classifications (send_id) WHERE send_id IS NOT NULL;
