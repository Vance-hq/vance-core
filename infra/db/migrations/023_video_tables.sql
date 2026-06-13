-- Video agent tables
CREATE TABLE IF NOT EXISTS video_scripts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product         TEXT NOT NULL,
    topic           TEXT NOT NULL,
    persona         TEXT NOT NULL DEFAULT '',
    script          TEXT NOT NULL,
    hook            TEXT NOT NULL DEFAULT '',
    duration_est_s  INTEGER NOT NULL DEFAULT 0,
    format          TEXT NOT NULL DEFAULT 'long',  -- long | short
    status          TEXT NOT NULL DEFAULT 'draft', -- draft | scheduled | published
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS video_performance (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id        TEXT NOT NULL,     -- external platform ID
    platform        TEXT NOT NULL DEFAULT 'youtube',
    title           TEXT NOT NULL DEFAULT '',
    views           INTEGER NOT NULL DEFAULT 0,
    watch_time_h    NUMERIC(10,2) NOT NULL DEFAULT 0,
    ctr             NUMERIC(6,4),
    avg_view_pct    NUMERIC(5,2),
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (video_id, platform)
);
