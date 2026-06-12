"""Postgres operations on grader_* tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class GraderDB:
    # ------------------------------------------------------------------
    # Audits
    # ------------------------------------------------------------------

    def insert_audit(
        self,
        business_name: str,
        place_id: str | None,
        address: str | None,
        contact_email: str,
        contact_name: str | None,
        overall_score: int,
        category_scores: dict[str, Any],
        recommendations: list[dict[str, Any]],
        raw_places_data: dict[str, Any],
    ) -> str:
        aid = str(uuid.uuid4())
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO grader_audits
                        (id, business_name, place_id, address, contact_email, contact_name,
                         overall_score, category_scores, recommendations, raw_places_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        aid, business_name, place_id, address, contact_email, contact_name,
                        overall_score,
                        psycopg2.extras.Json(category_scores),
                        psycopg2.extras.Json(recommendations),
                        psycopg2.extras.Json(raw_places_data),
                    ),
                )
        return aid

    def set_report_url(self, audit_id: str, url: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE grader_audits SET report_url = %s WHERE id = %s",
                    (url, audit_id),
                )

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM grader_audits WHERE id = %s", (audit_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def recent_audits_for_seo(self, days: int = 30) -> list[dict[str, Any]]:
        """Return anonymised audit rows for SEO page generation."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT overall_score, category_scores, raw_places_data->>'types' AS types,
                           raw_places_data->>'formatted_address' AS address, created_at
                    FROM grader_audits
                    WHERE created_at >= now() - (%s * INTERVAL '1 day')
                      AND overall_score > 0
                    ORDER BY created_at DESC
                    """,
                    (days,),
                )
                return [dict(r) for r in cur.fetchall()]

    def daily_audit_count(self) -> int:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM grader_audits WHERE created_at >= now() - INTERVAL '1 day'"
                )
                return cur.fetchone()[0]  # type: ignore[index]

    # ------------------------------------------------------------------
    # Leads
    # ------------------------------------------------------------------

    def create_lead(
        self,
        audit_id: str,
        email: str,
        contact_name: str | None = None,
        product_interest: str = "local_rank_grader",
    ) -> str:
        lid = str(uuid.uuid4())
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO grader_leads
                        (id, audit_id, email, contact_name, product_interest)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (audit_id, email) DO UPDATE SET updated_at = now()
                    RETURNING id
                    """,
                    (lid, audit_id, email, contact_name, product_interest),
                )
                row = cur.fetchone()
                return str(row[0]) if row else lid

    def get_lead(self, lead_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT l.*, a.business_name, a.overall_score, a.category_scores,
                           a.recommendations, a.report_url, a.raw_places_data
                    FROM grader_leads l
                    JOIN grader_audits a ON a.id = l.audit_id
                    WHERE l.id = %s
                    """,
                    (lead_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_lead_by_email_audit(self, audit_id: str, email: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM grader_leads WHERE audit_id = %s AND email = %s",
                    (audit_id, email),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def advance_sequence_step(self, lead_id: str) -> int:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE grader_leads SET sequence_step = sequence_step + 1, updated_at = now()
                    WHERE id = %s RETURNING sequence_step
                    """,
                    (lead_id,),
                )
                row = cur.fetchone()
                return row[0] if row else 0  # type: ignore[index]

    def add_score(self, lead_id: str, delta: int) -> int:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE grader_leads SET score = score + %s, updated_at = now()
                    WHERE id = %s RETURNING score
                    """,
                    (delta, lead_id),
                )
                row = cur.fetchone()
                return row[0] if row else 0  # type: ignore[index]

    def mark_trial_started(self, lead_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE grader_leads SET trial_started_at = now() WHERE id = %s AND trial_started_at IS NULL",
                    (lead_id,),
                )

    def daily_report_stats(self) -> dict[str, Any]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT l.id)                                AS total_leads,
                        COUNT(DISTINCT l.id) FILTER (WHERE l.trial_started_at IS NOT NULL) AS trials_started,
                        COUNT(DISTINCT l.id) FILTER (WHERE l.converted_at IS NOT NULL)     AS conversions,
                        AVG(a.overall_score)::NUMERIC(5,1)                  AS avg_score
                    FROM grader_leads l
                    JOIN grader_audits a ON a.id = l.audit_id
                    WHERE l.created_at >= now() - INTERVAL '1 day'
                    """
                )
                return dict(cur.fetchone() or {})

    def funnel_stats(self) -> dict[str, Any]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*)                                                            AS audits_total,
                        COUNT(*) FILTER (WHERE a.report_url IS NOT NULL)                   AS reports_delivered,
                        COUNT(DISTINCT l.id)                                               AS leads_created,
                        COUNT(DISTINCT l.id) FILTER (WHERE l.sequence_step > 1)            AS email_engaged,
                        COUNT(DISTINCT l.id) FILTER (WHERE l.trial_started_at IS NOT NULL) AS trials_started
                    FROM grader_audits a
                    LEFT JOIN grader_leads l ON l.audit_id = a.id
                    WHERE a.created_at >= now() - INTERVAL '7 day'
                    """
                )
                return dict(cur.fetchone() or {})

    def top_industries_cities(self, days: int = 7) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT
                        raw_places_data->>'types' AS industry,
                        raw_places_data->>'city'  AS city,
                        COUNT(*)                  AS count
                    FROM grader_audits
                    WHERE created_at >= now() - (%s * INTERVAL '1 day')
                    GROUP BY 1, 2
                    ORDER BY count DESC
                    LIMIT 20
                    """,
                    (days,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Benchmarks
    # ------------------------------------------------------------------

    def insert_benchmark(
        self,
        audit_id: str,
        competitor_name: str,
        competitor_place_id: str | None,
        competitor_score: int,
        competitor_address: str | None,
        category_scores: dict[str, Any],
    ) -> str:
        bid = str(uuid.uuid4())
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO grader_benchmarks
                        (id, audit_id, competitor_name, competitor_place_id,
                         competitor_score, competitor_address, category_scores)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        bid, audit_id, competitor_name, competitor_place_id,
                        competitor_score, competitor_address,
                        psycopg2.extras.Json(category_scores),
                    ),
                )
        return bid

    def get_benchmarks(self, audit_id: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM grader_benchmarks WHERE audit_id = %s ORDER BY competitor_score DESC",
                    (audit_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Email events
    # ------------------------------------------------------------------

    def record_email_event(
        self,
        lead_id: str,
        event_type: str,
        sequence_step: int | None,
        score_delta: int,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO grader_email_events (lead_id, event_type, sequence_step, score_delta)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (lead_id, event_type, sequence_step, score_delta),
                )
