"""Postgres helpers for the scaling agent."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class ScalingDB:

    # ------------------------------------------------------------------
    # resource_metrics
    # ------------------------------------------------------------------

    def insert_metric(
        self,
        *,
        metric_name: str,
        value: float,
        container: str = "",
        recorded_at: datetime | None = None,
    ) -> str:
        ts = recorded_at or datetime.now(timezone.utc)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO resource_metrics (metric_name, value, container, recorded_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (metric_name, value, container, ts),
                )
                return str(cur.fetchone()[0])

    def bulk_insert_metrics(self, rows: list[dict]) -> None:
        if not rows:
            return
        with get_db() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO resource_metrics (metric_name, value, container, recorded_at)
                    VALUES %s
                    """,
                    [
                        (
                            r["metric_name"],
                            r["value"],
                            r.get("container", ""),
                            r.get("recorded_at", datetime.now(timezone.utc)),
                        )
                        for r in rows
                    ],
                )

    def get_recent_metrics(
        self,
        metric_name: str,
        minutes: int = 5,
        container: str = "",
    ) -> list[dict]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT metric_name, value, container, recorded_at
                    FROM resource_metrics
                    WHERE metric_name = %s
                      AND container = %s
                      AND recorded_at >= NOW() - INTERVAL '%s minutes'
                    ORDER BY recorded_at DESC
                    """,
                    (metric_name, container, minutes),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_metric_history(
        self,
        metric_name: str,
        days: int = 90,
        container: str = "",
    ) -> list[dict]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT metric_name, value, container, recorded_at
                    FROM resource_metrics
                    WHERE metric_name = %s
                      AND container = %s
                      AND recorded_at >= NOW() - INTERVAL '%s days'
                    ORDER BY recorded_at ASC
                    """,
                    (metric_name, container, days),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_average_metric(self, metric_name: str, minutes: int = 5) -> float | None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT AVG(value) FROM resource_metrics
                    WHERE metric_name = %s
                      AND recorded_at >= NOW() - INTERVAL '%s minutes'
                    """,
                    (metric_name, minutes),
                )
                result = cur.fetchone()[0]
                return float(result) if result is not None else None

    # ------------------------------------------------------------------
    # scaling_events
    # ------------------------------------------------------------------

    def insert_event(
        self,
        *,
        trigger: str,
        action_taken: str,
        outcome: str,
        metadata: dict | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO scaling_events (trigger, action_taken, outcome, metadata)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (trigger, action_taken, outcome, psycopg2.extras.Json(metadata or {})),
                )
                return str(cur.fetchone()[0])

    def get_recent_events(self, hours: int = 24) -> list[dict]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM scaling_events
                    WHERE occurred_at >= NOW() - INTERVAL '%s hours'
                    ORDER BY occurred_at DESC
                    """,
                    (hours,),
                )
                return [dict(r) for r in cur.fetchall()]
