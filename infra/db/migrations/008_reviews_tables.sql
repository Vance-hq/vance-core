-- 008_reviews_tables.sql — Reviews agent: reviews, responses, requests, flags

CREATE TABLE IF NOT EXISTS reviews (
    id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform                TEXT        NOT NULL
                                        CHECK (platform IN ('google','yelp','facebook')),
    external_id             TEXT        NOT NULL,
    reviewer_name           TEXT        NOT NULL DEFAULT '',
    reviewer_review_count   INTEGER,
    reviewer_has_photo      BOOLEAN     NOT NULL DEFAULT FALSE,
    rating                  SMALLINT    NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_text             TEXT        NOT NULL DEFAULT '',
    posted_at               TIMESTAMPTZ NOT NULL,
    business                TEXT        NOT NULL,
    platform_ref            JSONB       NOT NULL DEFAULT '{}',
    responded_at            TIMESTAMPTZ,
    flagged                 BOOLEAN     NOT NULL DEFAULT FALSE,
    flag_confidence         REAL,
    flag_reason             TEXT,
    flag_reported           BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, external_id)
);

CREATE INDEX IF NOT EXISTS reviews_business_platform_idx  ON reviews (business, platform, posted_at DESC);
CREATE INDEX IF NOT EXISTS reviews_unanswered_idx         ON reviews (business, responded_at, posted_at DESC)
    WHERE responded_at IS NULL AND flagged = FALSE;
CREATE INDEX IF NOT EXISTS reviews_rolling_avg_idx        ON reviews (business, rating, posted_at DESC);

-- ---------------------------------------------------------------------------
-- review_responses
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_responses (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    review_id       UUID        NOT NULL REFERENCES reviews (id) ON DELETE CASCADE,
    response_text   TEXT        NOT NULL,
    posted_at       TIMESTAMPTZ,
    outcome         TEXT        CHECK (outcome IN ('posted','manual_post_required','failed','skipped')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS review_responses_review_idx ON review_responses (review_id);

-- ---------------------------------------------------------------------------
-- review_requests
-- Tracks outbound SMS/email requests asking customers to leave a review.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_requests (
    id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    contact_id      TEXT,
    job_id          TEXT        NOT NULL,
    business        TEXT        NOT NULL DEFAULT 'trusted_plumbing',
    phone           TEXT,
    email           TEXT,
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    review_posted_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id, business)
);

CREATE INDEX IF NOT EXISTS review_requests_job_idx ON review_requests (job_id, business);
