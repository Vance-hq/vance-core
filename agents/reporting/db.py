"""Reporting DB — brief_items and digests tables."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class ReportingDB:

    def add_brief_item(self, section: str, data: dict[str, Any], source: str, brief_date: str | None = None) -> str:
        today = brief_date or date.today().isoformat()
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO brief_items (section, data, source, brief_date)
                    VALUES (%s, %s, %s, %s) RETURNING id
                    """,
                    (section, json.dumps(data), source, today),
                )
                return str(cur.fetchone()["id"])

    def get_brief_items(self, brief_date: str | None = None) -> list[dict[str, Any]]:
        today = brief_date or date.today().isoformat()
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM brief_items WHERE brief_date = %s ORDER BY created_at",
                    (today,),
                )
                return [dict(r) for r in cur.fetchall()]

    def save_digest(self, period: str, period_date: str, content: str, recipients: list[str]) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO digests (period, period_date, content, recipients)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (period, period_date) DO UPDATE SET content = EXCLUDED.content
                    RETURNING id
                    """,
                    (period, period_date, content, json.dumps(recipients)),
                )
                return str(cur.fetchone()["id"])

    def mark_digest_sent(self, period: str, period_date: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE digests SET sent_at = NOW() WHERE period = %s AND period_date = %s",
                    (period, period_date),
                )

    def get_brief_items_range(self, from_date: str, to_date: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM brief_items
                    WHERE brief_date BETWEEN %s AND %s
                    ORDER BY brief_date, created_at
                    """,
                    (from_date, to_date),
                )
                return [dict(r) for r in cur.fetchall()]
