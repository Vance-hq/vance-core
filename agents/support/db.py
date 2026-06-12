"""
Support DB — support_tickets, nps_responses, kb_articles tables.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class SupportDB:

    # ------------------------------------------------------------------
    # support_tickets
    # ------------------------------------------------------------------

    def save_ticket(
        self,
        product: str,
        user_id: str,
        channel: str,
        classification: str,
        subject: str,
        body: str,
        status: str = "open",
        auto_resolved: bool = False,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO support_tickets
                        (product, user_id, channel, classification, subject, body,
                         status, auto_resolved)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (product, user_id, channel, classification, subject, body,
                     status, auto_resolved),
                )
                row = cur.fetchone()
        return str(row["id"])

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM support_tickets WHERE id = %s",
                    (ticket_id,),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def update_ticket(
        self,
        ticket_id: str,
        status: str,
        auto_resolved: bool = False,
        resolved_at: datetime | None = None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE support_tickets
                    SET status = %s,
                        auto_resolved = %s,
                        resolved_at = COALESCE(%s, resolved_at)
                    WHERE id = %s
                    """,
                    (status, auto_resolved, resolved_at, ticket_id),
                )

    def list_resolved_tickets(
        self,
        product: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM support_tickets
                    WHERE product = %s AND status = 'resolved'
                    ORDER BY resolved_at DESC
                    LIMIT %s
                    """,
                    (product, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # nps_responses
    # ------------------------------------------------------------------

    def save_nps_response(
        self,
        user_id: str,
        product: str,
        score: int,
        comment: str = "",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO nps_responses
                        (user_id, product, score, comment)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (user_id, product, score, comment),
                )
                row = cur.fetchone()
        return str(row["id"])

    def get_nps_responses(
        self,
        product: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM nps_responses
                    WHERE product = %s
                    ORDER BY recorded_at DESC
                    LIMIT %s
                    """,
                    (product, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # kb_articles
    # ------------------------------------------------------------------

    def save_kb_article(
        self,
        product: str,
        title: str,
        body: str,
        source_ticket_ids: list[str] | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO kb_articles
                        (product, title, body, source_ticket_ids)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (product, title, body, json.dumps(source_ticket_ids or [])),
                )
                row = cur.fetchone()
        return str(row["id"])

    def search_kb(
        self,
        product: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM kb_articles
                    WHERE product = %s
                      AND (title ILIKE %s OR body ILIKE %s)
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (product, f"%{query}%", f"%{query}%", limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_all_kb_articles(self, product: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM kb_articles WHERE product = %s ORDER BY updated_at DESC",
                    (product,),
                )
                return [dict(r) for r in cur.fetchall()]
