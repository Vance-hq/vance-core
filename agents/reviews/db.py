"""DB helpers for the reviews agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class ReviewsDB:

    # ------------------------------------------------------------------
    # Reviews
    # ------------------------------------------------------------------

    def review_exists(self, platform: str, external_id: str) -> bool:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM reviews WHERE platform = %s AND external_id = %s",
                    (platform, external_id),
                )
                return cur.fetchone() is not None

    def upsert_review(
        self,
        platform: str,
        external_id: str,
        reviewer_name: str,
        rating: int,
        review_text: str,
        posted_at: datetime,
        business: str,
        platform_ref: dict[str, Any] | None = None,
        reviewer_review_count: int | None = None,
        reviewer_has_photo: bool = False,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO reviews
                        (id, platform, external_id, reviewer_name, reviewer_review_count,
                         reviewer_has_photo, rating, review_text, posted_at, business, platform_ref)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (platform, external_id) DO UPDATE
                        SET reviewer_name         = EXCLUDED.reviewer_name,
                            reviewer_review_count = EXCLUDED.reviewer_review_count,
                            reviewer_has_photo    = EXCLUDED.reviewer_has_photo,
                            rating                = EXCLUDED.rating,
                            review_text           = EXCLUDED.review_text,
                            platform_ref          = EXCLUDED.platform_ref
                    RETURNING id
                    """,
                    (
                        row_id,
                        platform,
                        external_id,
                        reviewer_name,
                        reviewer_review_count,
                        reviewer_has_photo,
                        rating,
                        review_text,
                        posted_at,
                        business,
                        psycopg2.extras.Json(platform_ref or {}),
                    ),
                )
                result = cur.fetchone()
                conn.commit()
                return str(result[0]) if result else row_id

    def get_review(self, review_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM reviews WHERE id = %s", (review_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def unanswered_reviews(self, business: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if business:
                    cur.execute(
                        """
                        SELECT * FROM reviews
                        WHERE responded_at IS NULL
                          AND flagged = FALSE
                          AND business = %s
                        ORDER BY posted_at DESC
                        LIMIT %s
                        """,
                        (business, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT * FROM reviews
                        WHERE responded_at IS NULL AND flagged = FALSE
                        ORDER BY posted_at DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                return [dict(r) for r in cur.fetchall()]

    def mark_responded(self, review_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE reviews SET responded_at = now() WHERE id = %s",
                    (review_id,),
                )
                conn.commit()

    def flag_review(
        self,
        review_id: str,
        reason: str,
        confidence: float,
        auto_reported: bool = False,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE reviews
                    SET flagged = TRUE,
                        flag_confidence = %s,
                        flag_reason     = %s,
                        flag_reported   = %s
                    WHERE id = %s
                    """,
                    (confidence, reason, auto_reported, review_id),
                )
                conn.commit()

    def reviews_for_fake_scan(self, limit: int = 100) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM reviews
                    WHERE flagged = FALSE
                      AND flag_confidence IS NULL
                    ORDER BY posted_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(r) for r in cur.fetchall()]

    def rolling_average(self, business: str, days: int = 30) -> float | None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT AVG(rating)::FLOAT
                    FROM reviews
                    WHERE business = %s
                      AND posted_at > now() - (%s || ' days')::INTERVAL
                      AND flagged = FALSE
                    """,
                    (business, days),
                )
                row = cur.fetchone()
                return float(row[0]) if row and row[0] is not None else None

    def recent_review_count(self, business: str, days: int = 30) -> int:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM reviews
                    WHERE business = %s
                      AND posted_at > now() - (%s || ' days')::INTERVAL
                      AND flagged = FALSE
                    """,
                    (business, days),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Review responses
    # ------------------------------------------------------------------

    def log_response(
        self,
        review_id: str,
        response_text: str,
        posted_at: datetime | None,
        outcome: str,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO review_responses (id, review_id, response_text, posted_at, outcome)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (row_id, review_id, response_text, posted_at, outcome),
                )
                conn.commit()
                return row_id

    # ------------------------------------------------------------------
    # Review requests
    # ------------------------------------------------------------------

    def review_request_sent(self, job_id: str, business: str = "trusted_plumbing") -> bool:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM review_requests WHERE job_id = %s AND business = %s",
                    (job_id, business),
                )
                return cur.fetchone() is not None

    def log_review_request(
        self,
        job_id: str,
        business: str = "trusted_plumbing",
        contact_id: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO review_requests (id, contact_id, job_id, business, phone, email)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (job_id, business) DO NOTHING
                    """,
                    (row_id, contact_id, job_id, business, phone, email),
                )
                conn.commit()
                return row_id

    def mark_review_posted(self, job_id: str, business: str = "trusted_plumbing") -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE review_requests
                    SET review_posted_at = now()
                    WHERE job_id = %s AND business = %s
                    """,
                    (job_id, business),
                )
                conn.commit()
