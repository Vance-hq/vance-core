-- 013_security_tables.sql — Security agent: uptime_log, security_events,
--   vulnerability_findings, ssl_certs, access_audit

-- ---------------------------------------------------------------------------
-- uptime_log
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS uptime_log (
    id               UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    service          TEXT        NOT NULL,
    status           INTEGER,
    response_time_ms INTEGER,
    ok               BOOLEAN     NOT NULL,
    error            TEXT,
    checked_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS uptime_log_service_idx     ON uptime_log (service, checked_at DESC);
CREATE INDEX IF NOT EXISTS uptime_log_failures_idx    ON uptime_log (checked_at DESC) WHERE ok = false;

-- ---------------------------------------------------------------------------
-- security_events
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS security_events (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type   TEXT        NOT NULL,
    severity     TEXT        NOT NULL
                 CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW','INFO')),
    source_ip    TEXT,
    target       TEXT,
    action_taken TEXT,
    details      JSONB       NOT NULL DEFAULT '{}',
    detected_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS security_events_type_idx     ON security_events (event_type, detected_at DESC);
CREATE INDEX IF NOT EXISTS security_events_severity_idx ON security_events (severity, detected_at DESC);
CREATE INDEX IF NOT EXISTS security_events_ip_idx       ON security_events (source_ip) WHERE source_ip IS NOT NULL;

-- ---------------------------------------------------------------------------
-- vulnerability_findings
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS vulnerability_findings (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    repo        TEXT        NOT NULL,
    package     TEXT        NOT NULL,
    cve_id      TEXT,
    cvss_score  NUMERIC(4,1),
    severity    TEXT        NOT NULL
                CHECK (severity IN ('CRITICAL','HIGH','MEDIUM','LOW')),
    status      TEXT        NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','patched','accepted_risk','false_positive')),
    scan_type   TEXT        NOT NULL,
    details     JSONB       NOT NULL DEFAULT '{}',
    found_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS vuln_findings_repo_idx     ON vulnerability_findings (repo, found_at DESC);
CREATE INDEX IF NOT EXISTS vuln_findings_severity_idx ON vulnerability_findings (severity, status) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS vuln_findings_cve_idx      ON vulnerability_findings (cve_id) WHERE cve_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- ssl_certs
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ssl_certs (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain       TEXT        NOT NULL UNIQUE,
    expires_at   TIMESTAMPTZ,
    last_checked TIMESTAMPTZ NOT NULL DEFAULT now(),
    auto_renew   BOOLEAN     NOT NULL DEFAULT false,
    issuer       TEXT,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS ssl_certs_expiry_idx ON ssl_certs (expires_at) WHERE expires_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- access_audit
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS access_audit (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    service      TEXT        NOT NULL,
    account      TEXT        NOT NULL,
    access_level TEXT        NOT NULL,
    last_used    TIMESTAMPTZ,
    flagged      BOOLEAN     NOT NULL DEFAULT false,
    flag_reason  TEXT,
    reviewed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS access_audit_service_idx  ON access_audit (service, reviewed_at DESC);
CREATE INDEX IF NOT EXISTS access_audit_flagged_idx  ON access_audit (flagged, reviewed_at DESC) WHERE flagged = true;
