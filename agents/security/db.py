"""DB helpers for the security agent — all five security tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class SecurityDB:

    # ------------------------------------------------------------------
    # uptime_log
    # ------------------------------------------------------------------

    def log_uptime(
        self,
        service: str,
        ok: bool,
        status: int | None = None,
        response_time_ms: int | None = None,
        error: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO uptime_log (id, service, status, response_time_ms, ok, error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, service, status, response_time_ms, ok, error),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_recent_downtime(self, hours: int = 1, service: str | None = None) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters = ["ok = false", "checked_at > now() - interval '%s hours'"]
                params: list[Any] = [hours]
                if service:
                    filters.append("service = %s")
                    params.append(service)
                cur.execute(
                    f"SELECT * FROM uptime_log WHERE {' AND '.join(filters)} ORDER BY checked_at DESC",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # security_events
    # ------------------------------------------------------------------

    def save_event(
        self,
        event_type: str,
        severity: str,
        source_ip: str | None = None,
        target: str | None = None,
        action_taken: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO security_events
                        (id, event_type, severity, source_ip, target, action_taken, details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, event_type, severity, source_ip, target, action_taken,
                     psycopg2.extras.Json(details or {})),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_events(
        self,
        event_type: str | None = None,
        severity: str | None = None,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters = ["detected_at > now() - interval '%s hours'"]
                params: list[Any] = [hours]
                if event_type:
                    filters.append("event_type = %s")
                    params.append(event_type)
                if severity:
                    filters.append("severity = %s")
                    params.append(severity)
                cur.execute(
                    f"SELECT * FROM security_events WHERE {' AND '.join(filters)} ORDER BY detected_at DESC",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # vulnerability_findings
    # ------------------------------------------------------------------

    def save_vulnerability(
        self,
        repo: str,
        package: str,
        severity: str,
        scan_type: str,
        cve_id: str | None = None,
        cvss_score: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO vulnerability_findings
                        (id, repo, package, cve_id, cvss_score, severity, scan_type, details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    (row_id, repo, package, cve_id, cvss_score, severity, scan_type,
                     psycopg2.extras.Json(details or {})),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_open_vulns(self, repo: str | None = None, severity: str | None = None) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters = ["status = 'open'"]
                params: list[Any] = []
                if repo:
                    filters.append("repo = %s")
                    params.append(repo)
                if severity:
                    filters.append("severity = %s")
                    params.append(severity)
                cur.execute(
                    f"SELECT * FROM vulnerability_findings WHERE {' AND '.join(filters)} ORDER BY found_at DESC",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # ssl_certs
    # ------------------------------------------------------------------

    def upsert_ssl_cert(
        self,
        domain: str,
        expires_at: datetime | None,
        auto_renew: bool = False,
        issuer: str | None = None,
        error: str | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ssl_certs (id, domain, expires_at, auto_renew, issuer, error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (domain) DO UPDATE SET
                        expires_at   = EXCLUDED.expires_at,
                        last_checked = now(),
                        auto_renew   = EXCLUDED.auto_renew,
                        issuer       = EXCLUDED.issuer,
                        error        = EXCLUDED.error
                    """,
                    (str(uuid.uuid4()), domain, expires_at, auto_renew, issuer, error),
                )
                conn.commit()

    def get_expiring_certs(self, within_days: int = 30) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM ssl_certs
                    WHERE expires_at IS NOT NULL
                      AND expires_at < now() + interval '%s days'
                    ORDER BY expires_at ASC
                    """,
                    (within_days,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # access_audit
    # ------------------------------------------------------------------

    def save_access_audit(
        self,
        service: str,
        account: str,
        access_level: str,
        last_used: datetime | None = None,
        flagged: bool = False,
        flag_reason: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO access_audit
                        (id, service, account, access_level, last_used, flagged, flag_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, service, account, access_level, last_used, flagged, flag_reason),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_flagged_accounts(self, service: str | None = None) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters = ["flagged = true"]
                params: list[Any] = []
                if service:
                    filters.append("service = %s")
                    params.append(service)
                cur.execute(
                    f"SELECT * FROM access_audit WHERE {' AND '.join(filters)} ORDER BY reviewed_at DESC",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    def get_last_backup_timestamp(self) -> datetime | None:
        """Return the most recent successful backup timestamp from backup_runs table."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT completed_at FROM backup_runs
                    WHERE status = 'success'
                    ORDER BY completed_at DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                return row[0] if row else None
