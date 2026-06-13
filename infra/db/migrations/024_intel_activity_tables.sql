-- Intel agent — competitor activity, community signals, opportunities
CREATE TABLE IF NOT EXISTS competitor_activity (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor      TEXT NOT NULL,
    activity_type   TEXT NOT NULL,  -- pricing_change | blog_post | linkedin_post | job_listing | review_trend | screenshot_diff
    summary         TEXT NOT NULL,
    source_url      TEXT NOT NULL DEFAULT '',
    product         TEXT NOT NULL DEFAULT '',
    content_hash    TEXT NOT NULL DEFAULT '',  -- hash of page content for change detection
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actioned        BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_competitor_activity_competitor ON competitor_activity (competitor, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_competitor_activity_actioned ON competitor_activity (actioned, detected_at DESC);

-- Store latest content hash per competitor+page to detect changes
CREATE TABLE IF NOT EXISTS competitor_page_hashes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor      TEXT NOT NULL,
    page_type       TEXT NOT NULL,   -- pricing | blog | jobs | reviews
    url             TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    screenshot_path TEXT NOT NULL DEFAULT '',
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor, page_type)
);

CREATE TABLE IF NOT EXISTS community_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform        TEXT NOT NULL,  -- reddit | facebook | linkedin
    post_url        TEXT NOT NULL DEFAULT '',
    signal_type     TEXT NOT NULL,  -- recommendation_request | competitor_complaint | general_mention
    summary         TEXT NOT NULL,
    relevance_score INTEGER NOT NULL DEFAULT 5,  -- 1-10
    subreddit       TEXT NOT NULL DEFAULT '',
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actioned        BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (platform, post_url)
);
CREATE INDEX IF NOT EXISTS idx_community_signals_type ON community_signals (signal_type, detected_at DESC);

CREATE TABLE IF NOT EXISTS opportunities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type            TEXT NOT NULL,  -- product_hunt | api_integration | affiliate | partnership
    description     TEXT NOT NULL,
    source_url      TEXT NOT NULL DEFAULT '',
    score           INTEGER NOT NULL DEFAULT 0,  -- 1-10 LLM-rated
    relevance       INTEGER NOT NULL DEFAULT 0,
    effort          TEXT NOT NULL DEFAULT 'medium',  -- low | medium | high
    potential_impact TEXT NOT NULL DEFAULT 'medium',
    status          TEXT NOT NULL DEFAULT 'new',   -- new | reviewed | actioned | dismissed
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_opportunities_score ON opportunities (score DESC, detected_at DESC);

-- Store press mentions separately from intel_signals
CREATE TABLE IF NOT EXISTS press_mentions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keyword         TEXT NOT NULL,
    headline        TEXT NOT NULL,
    source          TEXT NOT NULL,
    url             TEXT NOT NULL DEFAULT '',
    snippet         TEXT NOT NULL DEFAULT '',
    sentiment       TEXT NOT NULL DEFAULT 'neutral',  -- positive | negative | neutral
    routed_to       TEXT NOT NULL DEFAULT '',         -- content | strategy | ''
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (url)
);
