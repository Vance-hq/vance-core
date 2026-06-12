"""Postgres helpers for analytics snapshots, reports, and anomaly log."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class AnalyticsDB:
    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def insert_snapshot(
        self,
        *,
        metric_type: str,
        metric_value: float,
        source: str,
        metadata: dict | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analytics_snapshots
                        (metric_type, metric_value, source, metadata, period_start, period_end)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        metric_type,
                        metric_value,
                        source,
                        psycopg2.extras.Json(metadata or {}),
                        period_start,
                        period_end,
                    ),
                )
                return str(cur.fetchone()[0])

    def bulk_insert_snapshots(self, rows: list[dict]) -> None:
        """Insert multiple snapshot rows in one round-trip."""
        if not rows:
            return
        with get_db() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO analytics_snapshots
                        (metric_type, metric_value, source, metadata)
                    VALUES %s
                    """,
                    [
                        (
                            r["metric_type"],
                            r["metric_value"],
                            r["source"],
                            psycopg2.extras.Json(r.get("metadata", {})),
                        )
                        for r in rows
                    ],
                )

    def get_latest_snapshot(self, metric_type: str) -> dict | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM analytics_snapshots
                    WHERE metric_type = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (metric_type,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_metric_average(self, metric_type: str, days: int = 7) -> float | None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT AVG(metric_value) FROM analytics_snapshots
                    WHERE metric_type = %s
                      AND created_at >= NOW() - INTERVAL '%s days'
                    """,
                    (metric_type, days),
                )
                result = cur.fetchone()[0]
                return float(result) if result is not None else None

    def get_metric_history(
        self,
        metric_type: str,
        days: int = 30,
        limit: int = 100,
    ) -> list[dict]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT metric_value, metadata, created_at FROM analytics_snapshots
                    WHERE metric_type = %s
                      AND created_at >= NOW() - INTERVAL '%s days'
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (metric_type, days, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def upsert_report(
        self,
        report_type: str,
        content: dict,
        ttl_seconds: int = 3600,
    ) -> str:
        expires = datetime.now(timezone.utc).timestamp() + ttl_seconds
        expires_dt = datetime.fromtimestamp(expires, tz=timezone.utc)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analytics_reports (report_type, content, expires_at)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (report_type, psycopg2.extras.Json(content), expires_dt),
                )
                return str(cur.fetchone()[0])

    def get_cached_report(self, report_type: str) -> dict | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT content FROM analytics_reports
                    WHERE report_type = %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY generated_at DESC
                    LIMIT 1
                    """,
                    (report_type,),
                )
                row = cur.fetchone()
                return dict(row["content"]) if row else None

    # ------------------------------------------------------------------
    # Anomalies
    # ------------------------------------------------------------------

    def insert_anomaly(
        self,
        metric_type: str,
        current_val: float,
        baseline_val: float,
        change_pct: float,
        alerted: bool = False,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO analytics_anomalies
                        (metric_type, current_val, baseline_val, change_pct, alerted)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (metric_type, current_val, baseline_val, change_pct, alerted),
                )
                return str(cur.fetchone()[0])
