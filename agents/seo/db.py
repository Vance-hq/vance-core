"""DB helpers for the SEO agent — gbp_audits, keyword_rankings, seo_tasks."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class SeoDB:

    # ------------------------------------------------------------------
    # gbp_audits
    # ------------------------------------------------------------------

    def save_gbp_audit(
        self,
        business: str,
        score: int,
        issues_found: int,
        issues_fixed: int,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO gbp_audits
                        (id, business, audit_date, score, issues_found, issues_fixed)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, business, date.today(), score, issues_found, issues_fixed),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_last_gbp_audit(self, business: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM gbp_audits WHERE business = %s ORDER BY audit_date DESC LIMIT 1",
                    (business,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_gbp_audit_history(self, business: str, limit: int = 10) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM gbp_audits WHERE business = %s ORDER BY audit_date DESC LIMIT %s",
                    (business, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # keyword_rankings
    # ------------------------------------------------------------------

    def save_keyword_ranking(
        self,
        product: str,
        keyword: str,
        rank: int,
        url: str,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO keyword_rankings
                        (id, product, keyword, rank, url, recorded_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, product, keyword, rank, url,
                     datetime.now(timezone.utc)),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_previous_rankings(
        self,
        product: str,
        keyword: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM keyword_rankings
                    WHERE product = %s AND keyword = %s
                    ORDER BY recorded_at DESC
                    LIMIT %s
                    """,
                    (product, keyword, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_top_keywords(
        self,
        product: str,
        max_rank: int = 10,
    ) -> list[dict[str, Any]]:
        """Return most-recent ranking row per keyword, filtered to top N."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT DISTINCT ON (keyword) *
                    FROM keyword_rankings
                    WHERE product = %s
                    ORDER BY keyword, recorded_at DESC
                    """,
                    (product,),
                )
                rows = [dict(r) for r in cur.fetchall()]
                return [r for r in rows if r.get("rank", 999) <= max_rank]

    # ------------------------------------------------------------------
    # seo_tasks
    # ------------------------------------------------------------------

    def save_seo_task(
        self,
        product: str,
        task_type: str,
        url: str,
        status: str = "pending",
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO seo_tasks
                        (id, product, task_type, url, status)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, product, task_type, url, status),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def update_seo_task(
        self,
        task_id: str,
        status: str | None = None,
        improvement_delta: int | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE seo_tasks
                    SET status            = COALESCE(%s, status),
                        improvement_delta = COALESCE(%s, improvement_delta),
                        completed_at      = CASE WHEN %s = 'completed' THEN now() ELSE completed_at END
                    WHERE id = %s
                    """,
                    (status, improvement_delta, status, task_id),
                )
                conn.commit()

    def get_pending_tasks(self, product: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM seo_tasks WHERE product = %s AND status = 'pending' ORDER BY id",
                    (product,),
                )
                return [dict(r) for r in cur.fetchall()]
