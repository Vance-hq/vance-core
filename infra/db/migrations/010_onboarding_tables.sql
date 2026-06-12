-- 010_onboarding_tables.sql — Onboarding agent: onboarding_state, activation_events

-- ---------------------------------------------------------------------------
-- onboarding_state
-- One row per (user, product) pair. Created on signup; updated as milestones hit.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS onboarding_state (
    id                   UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id              TEXT        NOT NULL,
    product              TEXT        NOT NULL,
    current_milestone    TEXT        NOT NULL DEFAULT '',
    milestones_completed JSONB       NOT NULL DEFAULT '[]',
    last_nudge_at        TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, product)
);

CREATE INDEX IF NOT EXISTS onboarding_state_product_idx ON onboarding_state (product, created_at DESC);
CREATE INDEX IF NOT EXISTS onboarding_state_stuck_idx   ON onboarding_state (created_at ASC)
    WHERE milestones_completed = '[]'::jsonb;

-- ---------------------------------------------------------------------------
-- activation_events
-- Immutable log of every milestone hit — one row per achievement.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS activation_events (
    id               UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          TEXT        NOT NULL,
    product          TEXT        NOT NULL,
    milestone        TEXT        NOT NULL,
    achieved_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    days_since_signup INTEGER     NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS activation_events_user_idx      ON activation_events (user_id, achieved_at DESC);
CREATE INDEX IF NOT EXISTS activation_events_product_idx   ON activation_events (product, achieved_at DESC);
CREATE INDEX IF NOT EXISTS activation_events_milestone_idx ON activation_events (product, milestone, achieved_at DESC);
