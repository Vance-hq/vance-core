-- 007_sales_tables.sql — Sales agent: users, sales_actions, churn_recovery_attempts

-- ---------------------------------------------------------------------------
-- users
-- One row per SaaS product user. Created on signup; updated on login/convert/churn.
-- Shared across all products; product column disambiguates.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id                  UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    email               TEXT        NOT NULL,
    product             TEXT        NOT NULL,
    plan                TEXT        NOT NULL DEFAULT 'trial'
                                    CHECK (plan IN ('trial','free','starter','pro','enterprise')),
    trial_started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at       TIMESTAMPTZ,
    converted_at        TIMESTAMPTZ,
    churned_at          TIMESTAMPTZ,
    stripe_customer_id  TEXT,
    stripe_sub_id       TEXT,
    nps_score           SMALLINT,
    engagement_score    INTEGER     NOT NULL DEFAULT 0,
    company             TEXT,
    role                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (email, product)
);

CREATE INDEX IF NOT EXISTS users_product_idx         ON users (product, created_at DESC);
CREATE INDEX IF NOT EXISTS users_plan_idx            ON users (plan);
CREATE INDEX IF NOT EXISTS users_churned_idx         ON users (churned_at) WHERE churned_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS users_trial_idx           ON users (trial_started_at) WHERE converted_at IS NULL;
CREATE INDEX IF NOT EXISTS users_stripe_customer_idx ON users (stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- user_feature_attempts
-- Logged whenever a user hits a plan-gated feature.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS user_feature_attempts (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    feature         TEXT        NOT NULL,
    blocked_by_plan BOOLEAN     NOT NULL DEFAULT TRUE,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_feature_attempts_user_idx  ON user_feature_attempts (user_id, attempted_at DESC);
CREATE INDEX IF NOT EXISTS user_feature_attempts_feat_idx  ON user_feature_attempts (feature, attempted_at DESC);

-- ---------------------------------------------------------------------------
-- sales_actions
-- One row per sales touchpoint (nudge, recovery, referral invite, win-back).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sales_actions (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id  UUID,                       -- NULL if keyed only by email
    user_id     UUID        REFERENCES users (id) ON DELETE SET NULL,
    product     TEXT        NOT NULL,
    action_type TEXT        NOT NULL
                CHECK (action_type IN (
                    'trial_nudge','upgrade_nudge','churn_recovery',
                    'win_back','referral_invite','pricing_intel_alert'
                )),
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome     TEXT,                       -- 'converted','ignored','replied','bounced' etc.
    meta        JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS sales_actions_user_idx    ON sales_actions (user_id, sent_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sales_actions_type_idx    ON sales_actions (action_type, sent_at DESC);
CREATE INDEX IF NOT EXISTS sales_actions_product_idx ON sales_actions (product, sent_at DESC);

-- ---------------------------------------------------------------------------
-- churn_recovery_attempts
-- Richer record for every churn recovery effort — tracks outcomes over time.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS churn_recovery_attempts (
    id                UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id           UUID        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    product           TEXT        NOT NULL,
    attempt_date      TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome           TEXT        CHECK (outcome IN ('recovered','no_response','declined')),
    days_to_respond   INTEGER,
    extension_applied BOOLEAN     NOT NULL DEFAULT FALSE,
    stripe_coupon_id  TEXT
);

CREATE INDEX IF NOT EXISTS churn_recovery_user_idx ON churn_recovery_attempts (user_id, attempt_date DESC);
CREATE INDEX IF NOT EXISTS churn_recovery_date_idx ON churn_recovery_attempts (attempt_date DESC);
