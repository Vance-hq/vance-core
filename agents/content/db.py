"""DB helpers for the content agent — content_pieces and content_calendar."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class ContentDB:

    # ------------------------------------------------------------------
    # content_pieces
    # ------------------------------------------------------------------

    def save_piece(
        self,
        product: str,
        platform: str,
        content_type: str,
        title: str,
        body: str,
        status: str = "draft",
        published_at: datetime | None = None,
        url: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO content_pieces
                        (id, product, platform, type, title, body, status, published_at, url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, product, platform, content_type, title, body,
                     status, published_at, url),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def update_piece(
        self,
        piece_id: str,
        status: str | None = None,
        url: str | None = None,
        published_at: datetime | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE content_pieces
                    SET status       = COALESCE(%s, status),
                        url          = COALESCE(%s, url),
                        published_at = COALESCE(%s, published_at)
                    WHERE id = %s
                    """,
                    (status, url, published_at, piece_id),
                )
                conn.commit()

    def get_piece(self, piece_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM content_pieces WHERE id = %s", (piece_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_recent_pieces(
        self,
        product: str,
        platform: str | None = None,
        content_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters = ["product = %s"]
                params: list[Any] = [product]
                if platform:
                    filters.append("platform = %s")
                    params.append(platform)
                if content_type:
                    filters.append("type = %s")
                    params.append(content_type)
                params.append(limit)
                cur.execute(
                    f"SELECT * FROM content_pieces WHERE {' AND '.join(filters)} "
                    "ORDER BY created_at DESC NULLS LAST LIMIT %s",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # content_calendar
    # ------------------------------------------------------------------

    def save_calendar_entry(
        self,
        product: str,
        scheduled_date: date,
        platform: str,
        content_type: str,
        topic: str,
        status: str = "pending",
        content_id: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO content_calendar
                        (id, product, scheduled_date, platform, type, topic, status, content_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (row_id, product, scheduled_date, platform, content_type,
                     topic, status, content_id),
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else row_id

    def get_calendar_entries(
        self,
        product: str,
        status: str | None = None,
        from_date: date | None = None,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters = ["product = %s"]
                params: list[Any] = [product]
                if status:
                    filters.append("status = %s")
                    params.append(status)
                if from_date:
                    filters.append("scheduled_date >= %s")
                    params.append(from_date)
                cur.execute(
                    f"SELECT * FROM content_calendar WHERE {' AND '.join(filters)} "
                    "ORDER BY scheduled_date ASC",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    def update_calendar_entry(
        self,
        entry_id: str,
        status: str | None = None,
        content_id: str | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE content_calendar
                    SET status     = COALESCE(%s, status),
                        content_id = COALESCE(%s, content_id)
                    WHERE id = %s
                    """,
                    (status, content_id, entry_id),
                )
                conn.commit()
