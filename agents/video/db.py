"""Video DB — video_scripts and video_performance tables."""

from __future__ import annotations

from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class VideoDB:

    def save_script(
        self,
        product: str,
        topic: str,
        persona: str,
        script: str,
        hook: str,
        duration_est_s: int,
        fmt: str = "long",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO video_scripts
                        (product, topic, persona, script, hook, duration_est_s, format)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (product, topic, persona, script, hook, duration_est_s, fmt),
                )
                return str(cur.fetchone()["id"])

    def update_script_status(self, script_id: str, status: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE video_scripts SET status = %s WHERE id = %s",
                    (status, script_id),
                )

    def list_scripts(self, product: str, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if status:
                    cur.execute(
                        "SELECT * FROM video_scripts WHERE product = %s AND status = %s ORDER BY created_at DESC LIMIT %s",
                        (product, status, limit),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM video_scripts WHERE product = %s ORDER BY created_at DESC LIMIT %s",
                        (product, limit),
                    )
                return [dict(r) for r in cur.fetchall()]

    def upsert_performance(
        self,
        video_id: str,
        platform: str,
        title: str,
        views: int,
        watch_time_h: float,
        ctr: float | None,
        avg_view_pct: float | None,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO video_performance
                        (video_id, platform, title, views, watch_time_h, ctr, avg_view_pct)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (video_id, platform) DO UPDATE SET
                        views        = EXCLUDED.views,
                        watch_time_h = EXCLUDED.watch_time_h,
                        ctr          = EXCLUDED.ctr,
                        avg_view_pct = EXCLUDED.avg_view_pct,
                        checked_at   = NOW()
                    """,
                    (video_id, platform, title, views, watch_time_h, ctr, avg_view_pct),
                )

    def list_performance(self, platform: str = "youtube", limit: int = 20) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM video_performance WHERE platform = %s ORDER BY views DESC LIMIT %s",
                    (platform, limit),
                )
                return [dict(r) for r in cur.fetchall()]
