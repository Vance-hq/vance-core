-- Migration 028: consolidated all-agent tables reference
-- Single-file combination of all agent table definitions.
-- All statements use CREATE TABLE IF NOT EXISTS so this is safe to re-run.
-- A shared users table anchors user-related foreign keys.

-- ---------------------------------------------------------------------------
-- Shared: users
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email             TEXT NOT NULL UNIQUE,
    product           TEXT NOT NULL CHECK (product IN ('starpio','oneserv','localoutrank','trusted_plumbing','vance_system')),
    stripe_customer_id TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email   ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_product ON users (product);

-- ---------------------------------------------------------------------------
-- Webhook tables (001)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS webhook_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source       TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}',
    processed    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_source    ON webhook_events (source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_events_processed ON webhook_events (processed) WHERE processed = FALSE;

-- ---------------------------------------------------------------------------
-- Forge — cold outreach (002)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS forge_leads (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_name TEXT NOT NULL,
    email         TEXT,
    phone         TEXT,
    website       TEXT,
    city          TEXT,
    niche         TEXT,
    score         FLOAT,
    status        TEXT NOT NULL DEFAULT 'new',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forge_leads_status ON forge_leads (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_forge_leads_niche  ON forge_leads (niche);

CREATE TABLE IF NOT EXISTS forge_sequences (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id     UUID NOT NULL REFERENCES forge_leads (id) ON DELETE CASCADE,
    step        INT NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active',
    next_send   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forge_sequences_lead   ON forge_sequences (lead_id);
CREATE INDEX IF NOT EXISTS idx_forge_sequences_next   ON forge_sequences (next_send) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS forge_emails (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sequence_id UUID NOT NULL REFERENCES forge_sequences (id) ON DELETE CASCADE,
    step        INT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    sent_at     TIMESTAMPTZ,
    opened_at   TIMESTAMPTZ,
    replied_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_forge_emails_sequence ON forge_emails (sequence_id, step);

-- ---------------------------------------------------------------------------
-- LocalRankGrader (003)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS grader_audits (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_name TEXT NOT NULL,
    place_id      TEXT,
    score         FLOAT,
    report_json   JSONB NOT NULL DEFAULT '{}',
    email         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_grader_audits_created  ON grader_audits (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_grader_audits_place_id ON grader_audits (place_id);

CREATE TABLE IF NOT EXISTS grader_conversions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id   UUID NOT NULL REFERENCES grader_audits (id) ON DELETE CASCADE,
    event      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_grader_conversions_audit ON grader_conversions (audit_id);

-- ---------------------------------------------------------------------------
-- Integrations (004)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS integration_calls (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service     TEXT NOT NULL,
    method      TEXT NOT NULL,
    request     JSONB NOT NULL DEFAULT '{}',
    response    JSONB,
    status_code INT,
    latency_ms  INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_integration_calls_service ON integration_calls (service, created_at DESC);

-- ---------------------------------------------------------------------------
-- Analytics (005 / 018)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_type TEXT NOT NULL,
    product       TEXT,
    data          JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_type    ON analytics_snapshots (snapshot_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_snapshots_product ON analytics_snapshots (product, created_at DESC);

CREATE TABLE IF NOT EXISTS analytics_anomalies (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric        TEXT NOT NULL,
    expected      FLOAT,
    actual        FLOAT,
    deviation_pct FLOAT,
    product       TEXT,
    acknowledged  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_anomalies_created ON analytics_anomalies (created_at DESC);

-- ---------------------------------------------------------------------------
-- Outreach (006)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS outreach_sequences (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id     TEXT NOT NULL,
    channel     TEXT NOT NULL DEFAULT 'linkedin',
    status      TEXT NOT NULL DEFAULT 'active',
    step        INT NOT NULL DEFAULT 0,
    next_send   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_sequences_lead   ON outreach_sequences (lead_id);
CREATE INDEX IF NOT EXISTS idx_outreach_sequences_status ON outreach_sequences (status, next_send);

CREATE TABLE IF NOT EXISTS outreach_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sequence_id UUID NOT NULL REFERENCES outreach_sequences (id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outreach_events_sequence ON outreach_events (sequence_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Sales (007)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sales_signals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users (id) ON DELETE SET NULL,
    product     TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    processed   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sales_signals_product ON sales_signals (product, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sales_signals_user    ON sales_signals (user_id) WHERE user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS sales_outreach_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID REFERENCES users (id) ON DELETE SET NULL,
    outreach_type TEXT NOT NULL,
    channel       TEXT NOT NULL,
    payload       JSONB NOT NULL DEFAULT '{}',
    sent_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sales_outreach_user ON sales_outreach_log (user_id, sent_at DESC);

-- ---------------------------------------------------------------------------
-- Reviews (008)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reviews (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform      TEXT NOT NULL,
    external_id   TEXT NOT NULL UNIQUE,
    author        TEXT,
    rating        INT,
    body          TEXT,
    replied       BOOLEAN NOT NULL DEFAULT FALSE,
    flagged       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reviews_platform ON reviews (platform, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reviews_unreplied ON reviews (replied) WHERE replied = FALSE;

CREATE TABLE IF NOT EXISTS review_responses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id   UUID NOT NULL REFERENCES reviews (id) ON DELETE CASCADE,
    draft       TEXT NOT NULL,
    posted_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_responses_review ON review_responses (review_id);

-- ---------------------------------------------------------------------------
-- Ads (009)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ad_campaigns (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform     TEXT NOT NULL,
    campaign_id  TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',
    budget       FLOAT,
    spend        FLOAT,
    roas         FLOAT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ad_campaigns_platform ON ad_campaigns (platform, status);

CREATE TABLE IF NOT EXISTS ad_performance_snapshots (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id  TEXT NOT NULL,
    impressions  INT,
    clicks       INT,
    conversions  INT,
    spend        FLOAT,
    roas         FLOAT,
    snapshot_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ad_perf_campaign ON ad_performance_snapshots (campaign_id, snapshot_at DESC);

-- ---------------------------------------------------------------------------
-- Onboarding (010)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS onboarding_flows (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users (id) ON DELETE CASCADE,
    product     TEXT NOT NULL,
    step        TEXT NOT NULL DEFAULT 'welcome',
    status      TEXT NOT NULL DEFAULT 'active',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_onboarding_user    ON onboarding_flows (user_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_product ON onboarding_flows (product, status);

CREATE TABLE IF NOT EXISTS onboarding_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_id     UUID NOT NULL REFERENCES onboarding_flows (id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_events_flow ON onboarding_events (flow_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Research (011)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS research_reports (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic         TEXT NOT NULL,
    report_type   TEXT NOT NULL,
    content       TEXT NOT NULL,
    product       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_reports_type    ON research_reports (report_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_reports_product ON research_reports (product, created_at DESC);

-- ---------------------------------------------------------------------------
-- Launch (012)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS launch_plans (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product     TEXT NOT NULL,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
    plan_json   JSONB NOT NULL DEFAULT '{}',
    launched_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_launch_plans_product ON launch_plans (product, status);

CREATE TABLE IF NOT EXISTS launch_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id     UUID NOT NULL REFERENCES launch_plans (id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_launch_events_plan ON launch_events (plan_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Security (013)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS security_checks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    check_type  TEXT NOT NULL,
    target      TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      JSONB NOT NULL DEFAULT '{}',
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_checks_type   ON security_checks (check_type, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_checks_status ON security_checks (status) WHERE status != 'ok';

CREATE TABLE IF NOT EXISTS security_alerts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type    TEXT NOT NULL,
    severity      TEXT NOT NULL DEFAULT 'medium',
    message       TEXT NOT NULL,
    acknowledged  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_alerts_unacked ON security_alerts (acknowledged) WHERE acknowledged = FALSE;

-- ---------------------------------------------------------------------------
-- Deploy (014)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS deployments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    environment   TEXT NOT NULL DEFAULT 'production',
    product       TEXT NOT NULL,
    version       TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    triggered_by  TEXT,
    deploy_log    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_deployments_product ON deployments (product, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_deployments_status  ON deployments (status) WHERE status IN ('pending','running');

-- ---------------------------------------------------------------------------
-- Finance (015)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS finance_snapshots (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_type TEXT NOT NULL,
    product       TEXT,
    period        TEXT NOT NULL,
    data          JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_finance_snapshots_type    ON finance_snapshots (snapshot_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_finance_snapshots_product ON finance_snapshots (product, created_at DESC);

CREATE TABLE IF NOT EXISTS finance_anomalies (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric        TEXT NOT NULL,
    expected      FLOAT,
    actual        FLOAT,
    product       TEXT,
    acknowledged  BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_finance_anomalies_created ON finance_anomalies (created_at DESC);

-- ---------------------------------------------------------------------------
-- Backup (016)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS backup_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backup_type TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'running',
    size_bytes  BIGINT,
    location    TEXT,
    verified    BOOLEAN NOT NULL DEFAULT FALSE,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_backup_runs_type   ON backup_runs (backup_type, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_runs_status ON backup_runs (status) WHERE status IN ('running','failed');

-- ---------------------------------------------------------------------------
-- Scaling (017)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scaling_metrics (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric      TEXT NOT NULL,
    value       FLOAT NOT NULL,
    threshold   FLOAT,
    breached    BOOLEAN NOT NULL DEFAULT FALSE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scaling_metrics_metric ON scaling_metrics (metric, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_scaling_metrics_breach ON scaling_metrics (breached) WHERE breached = TRUE;

CREATE TABLE IF NOT EXISTS scaling_remediations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action      TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    result      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scaling_remediations ON scaling_remediations (created_at DESC);

-- ---------------------------------------------------------------------------
-- Reporting (019 / 026)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS brief_items (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section      TEXT NOT NULL,
    content      TEXT NOT NULL,
    product      TEXT,
    source_agent TEXT,
    priority     INT NOT NULL DEFAULT 5,
    used         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_brief_items_section ON brief_items (section, used, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_brief_items_unused  ON brief_items (used) WHERE used = FALSE;

CREATE TABLE IF NOT EXISTS reports (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type  TEXT NOT NULL,
    product      TEXT,
    period_date  DATE,
    content_text TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_reports_type    ON reports (report_type, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_product ON reports (product, generated_at DESC);

CREATE TABLE IF NOT EXISTS alerts_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_agent  TEXT NOT NULL,
    alert_type    TEXT NOT NULL,
    message       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at  TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_alerts_log_undelivered   ON alerts_log (delivered_at) WHERE delivered_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_alerts_log_unacknowledged ON alerts_log (acknowledged_at) WHERE acknowledged_at IS NULL;

-- ---------------------------------------------------------------------------
-- Intel (020 / 024)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS intel_signals (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type   TEXT NOT NULL,
    source        TEXT NOT NULL,
    headline      TEXT NOT NULL,
    summary       TEXT,
    url           TEXT,
    relevance     FLOAT,
    processed     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intel_signals_type      ON intel_signals (signal_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_intel_signals_processed ON intel_signals (processed) WHERE processed = FALSE;

CREATE TABLE IF NOT EXISTS intel_digests (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    summary     TEXT NOT NULL,
    signal_ids  JSONB NOT NULL DEFAULT '[]',
    delivered   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intel_digests_created ON intel_digests (created_at DESC);

CREATE TABLE IF NOT EXISTS intel_competitor_activity (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competitor    TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    summary       TEXT NOT NULL,
    source_url    TEXT,
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intel_competitor_activity ON intel_competitor_activity (competitor, detected_at DESC);

-- ---------------------------------------------------------------------------
-- Strategy (021 / 027)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS strategy_signals (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product        TEXT NOT NULL,
    signal_type    TEXT NOT NULL,
    summary        TEXT NOT NULL,
    recommendation TEXT NOT NULL DEFAULT '',
    source_agent   TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_product ON strategy_signals (product, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_signals_type    ON strategy_signals (signal_type, created_at DESC);

CREATE TABLE IF NOT EXISTS strategy_insights (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    insight           TEXT NOT NULL,
    products_affected JSONB NOT NULL DEFAULT '[]',
    confidence        FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    actioned          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_insights_created  ON strategy_insights (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_strategy_insights_actioned ON strategy_insights (actioned) WHERE actioned = FALSE;

CREATE TABLE IF NOT EXISTS recommendations (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation TEXT NOT NULL,
    rationale      TEXT NOT NULL,
    agent_target   TEXT NOT NULL,
    confidence     FLOAT NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    executed       BOOLEAN NOT NULL DEFAULT FALSE,
    outcome        TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_recommendations_created    ON recommendations (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_recommendations_unexecuted ON recommendations (executed) WHERE executed = FALSE;

CREATE TABLE IF NOT EXISTS pivot_alerts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product            TEXT NOT NULL,
    diagnosis          TEXT NOT NULL,
    options            JSONB NOT NULL DEFAULT '[]',
    recommended_option TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pivot_alerts_product ON pivot_alerts (product, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pivot_alerts_pending ON pivot_alerts (status) WHERE status = 'pending';

-- ---------------------------------------------------------------------------
-- Memory (022)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS memory_entries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key         TEXT NOT NULL UNIQUE,
    value       TEXT NOT NULL,
    entry_type  TEXT NOT NULL DEFAULT 'fact',
    product     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_entries_type    ON memory_entries (entry_type);
CREATE INDEX IF NOT EXISTS idx_memory_entries_product ON memory_entries (product) WHERE product IS NOT NULL;

CREATE TABLE IF NOT EXISTS decision_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision    TEXT NOT NULL,
    rationale   TEXT,
    product     TEXT,
    outcome     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decision_log_created  ON decision_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_log_product  ON decision_log (product, created_at DESC);

-- ---------------------------------------------------------------------------
-- Video (023)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS video_scripts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    script      TEXT NOT NULL,
    product     TEXT,
    format      TEXT NOT NULL DEFAULT 'long',
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_scripts_product ON video_scripts (product, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_video_scripts_status  ON video_scripts (status);

CREATE TABLE IF NOT EXISTS video_performance (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    script_id     UUID REFERENCES video_scripts (id) ON DELETE SET NULL,
    platform      TEXT NOT NULL,
    video_id      TEXT,
    views         INT DEFAULT 0,
    likes         INT DEFAULT 0,
    comments      INT DEFAULT 0,
    watch_time_s  INT DEFAULT 0,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_performance_platform ON video_performance (platform, recorded_at DESC);

-- ---------------------------------------------------------------------------
-- Content & viral (no dedicated earlier migration — added here)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS content_pieces (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    content_type TEXT NOT NULL,
    product      TEXT,
    platform     TEXT,
    status       TEXT NOT NULL DEFAULT 'draft',
    published_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_pieces_product ON content_pieces (product, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_pieces_status  ON content_pieces (status);

CREATE TABLE IF NOT EXISTS viral_hooks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hook        TEXT NOT NULL,
    product     TEXT,
    score       FLOAT,
    used        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_viral_hooks_product ON viral_hooks (product, score DESC);

-- ---------------------------------------------------------------------------
-- SEO (no dedicated earlier migration — added here)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS seo_keywords (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keyword     TEXT NOT NULL,
    product     TEXT,
    volume      INT,
    difficulty  FLOAT,
    ranking     INT,
    tracked     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_keywords_product ON seo_keywords (product, ranking ASC NULLS LAST);

CREATE TABLE IF NOT EXISTS seo_audits (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url         TEXT NOT NULL,
    product     TEXT,
    score       FLOAT,
    issues      JSONB NOT NULL DEFAULT '[]',
    audited_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_seo_audits_product ON seo_audits (product, audited_at DESC);

-- ---------------------------------------------------------------------------
-- Support (no dedicated earlier migration — added here)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS support_tickets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users (id) ON DELETE SET NULL,
    product     TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    priority    TEXT NOT NULL DEFAULT 'normal',
    source      TEXT NOT NULL DEFAULT 'email',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_support_tickets_product ON support_tickets (product, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_support_tickets_user    ON support_tickets (user_id) WHERE user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS support_kb (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    product     TEXT,
    tags        JSONB NOT NULL DEFAULT '[]',
    published   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_support_kb_product ON support_kb (product, published);

-- ---------------------------------------------------------------------------
-- QA (no dedicated earlier migration — added here)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS qa_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_type    TEXT NOT NULL,
    product     TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    total       INT,
    passed      INT,
    failed      INT,
    report      JSONB NOT NULL DEFAULT '{}',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_qa_runs_product ON qa_runs (product, started_at DESC);

CREATE TABLE IF NOT EXISTS qa_bugs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'medium',
    product     TEXT,
    status      TEXT NOT NULL DEFAULT 'open',
    run_id      UUID REFERENCES qa_runs (id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qa_bugs_product ON qa_bugs (product, severity, status);
