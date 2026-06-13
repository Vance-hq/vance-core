"""Intel DB — intel_signals, keyword_trends, competitor_activity, community_signals, opportunities, press_mentions."""

from __future__ import annotations

from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class IntelDB:

    def save_signal(
        self,
        signal_type: str,
        headline: str,
        product: str = "",
        competitor: str = "",
        relevance_score: int = 5,
        summary: str = "",
        source_url: str = "",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO intel_signals
                        (signal_type, headline, product, competitor, relevance_score, summary, source_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (signal_type, headline, product, competitor, relevance_score, summary, source_url),
                )
                return str(cur.fetchone()["id"])

    def list_signals(self, product: str = "", min_relevance: int = 6, limit: int = 50) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if product:
                    cur.execute(
                        """
                        SELECT * FROM intel_signals
                        WHERE product = %s AND relevance_score >= %s
                        ORDER BY detected_at DESC LIMIT %s
                        """,
                        (product, min_relevance, limit),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM intel_signals WHERE relevance_score >= %s ORDER BY detected_at DESC LIMIT %s",
                        (min_relevance, limit),
                    )
                return [dict(r) for r in cur.fetchall()]

    def upsert_keyword_trend(self, keyword: str, product: str, trend_direction: str, volume_index: int) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO keyword_trends (keyword, product, trend_direction, volume_index)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (keyword, product) DO UPDATE SET
                        trend_direction = EXCLUDED.trend_direction,
                        volume_index    = EXCLUDED.volume_index,
                        checked_at      = NOW()
                    """,
                    (keyword, product, trend_direction, volume_index),
                )

    def list_keyword_trends(self, product: str, direction: str | None = None) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if direction:
                    cur.execute(
                        "SELECT * FROM keyword_trends WHERE product = %s AND trend_direction = %s ORDER BY volume_index DESC",
                        (product, direction),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM keyword_trends WHERE product = %s ORDER BY volume_index DESC",
                        (product,),
                    )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Competitor activity (migration 024)
    # ------------------------------------------------------------------

    def get_page_hash(self, competitor: str, page_type: str) -> str | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT content_hash FROM competitor_page_hashes WHERE competitor = %s AND page_type = %s",
                    (competitor, page_type),
                )
                row = cur.fetchone()
                return row["content_hash"] if row else None

    def upsert_page_hash(
        self,
        competitor: str,
        page_type: str,
        url: str,
        content_hash: str,
        screenshot_path: str = "",
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO competitor_page_hashes (competitor, page_type, url, content_hash, screenshot_path)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (competitor, page_type) DO UPDATE SET
                        content_hash    = EXCLUDED.content_hash,
                        screenshot_path = EXCLUDED.screenshot_path,
                        url             = EXCLUDED.url,
                        checked_at      = NOW()
                    """,
                    (competitor, page_type, url, content_hash, screenshot_path),
                )

    def save_competitor_activity(
        self,
        competitor: str,
        activity_type: str,
        summary: str,
        source_url: str = "",
        product: str = "",
        content_hash: str = "",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO competitor_activity
                        (competitor, activity_type, summary, source_url, product, content_hash)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (competitor, activity_type, summary, source_url, product, content_hash),
                )
                return str(cur.fetchone()["id"])

    def list_competitor_activities(
        self,
        competitor: str = "",
        product: str = "",
        limit: int = 50,
        unactioned_only: bool = False,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters = []
                params: list[Any] = []
                if competitor:
                    filters.append("competitor = %s")
                    params.append(competitor)
                if product:
                    filters.append("product = %s")
                    params.append(product)
                if unactioned_only:
                    filters.append("actioned = FALSE")
                where = ("WHERE " + " AND ".join(filters)) if filters else ""
                params.append(limit)
                cur.execute(
                    f"SELECT * FROM competitor_activity {where} ORDER BY detected_at DESC LIMIT %s",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Press mentions (migration 024)
    # ------------------------------------------------------------------

    def save_press_mention(
        self,
        keyword: str,
        headline: str,
        source: str,
        url: str,
        snippet: str = "",
        sentiment: str = "neutral",
        routed_to: str = "",
    ) -> str | None:
        """Returns new id or None if duplicate URL."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO press_mentions (keyword, headline, source, url, snippet, sentiment, routed_to)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING RETURNING id
                    """,
                    (keyword, headline, source, url, snippet, sentiment, routed_to),
                )
                row = cur.fetchone()
                return str(row["id"]) if row else None

    def list_press_mentions(self, sentiment: str = "", limit: int = 50) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if sentiment:
                    cur.execute(
                        "SELECT * FROM press_mentions WHERE sentiment = %s ORDER BY detected_at DESC LIMIT %s",
                        (sentiment, limit),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM press_mentions ORDER BY detected_at DESC LIMIT %s",
                        (limit,),
                    )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Community signals (migration 024)
    # ------------------------------------------------------------------

    def save_community_signal(
        self,
        platform: str,
        post_url: str,
        signal_type: str,
        summary: str,
        relevance_score: int = 5,
        subreddit: str = "",
    ) -> str | None:
        """Returns new id or None if duplicate (platform, post_url)."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO community_signals
                        (platform, post_url, signal_type, summary, relevance_score, subreddit)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (platform, post_url) DO NOTHING RETURNING id
                    """,
                    (platform, post_url, signal_type, summary, relevance_score, subreddit),
                )
                row = cur.fetchone()
                return str(row["id"]) if row else None

    def list_community_signals(
        self,
        signal_type: str = "",
        platform: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters, params = [], []
                if signal_type:
                    filters.append("signal_type = %s")
                    params.append(signal_type)
                if platform:
                    filters.append("platform = %s")
                    params.append(platform)
                where = ("WHERE " + " AND ".join(filters)) if filters else ""
                params.append(limit)
                cur.execute(
                    f"SELECT * FROM community_signals {where} ORDER BY detected_at DESC LIMIT %s",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Opportunities (migration 024)
    # ------------------------------------------------------------------

    def save_opportunity(
        self,
        type_: str,
        description: str,
        source_url: str = "",
        score: int = 0,
        relevance: int = 0,
        effort: str = "medium",
        potential_impact: str = "medium",
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO opportunities
                        (type, description, source_url, score, relevance, effort, potential_impact)
                    VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """,
                    (type_, description, source_url, score, relevance, effort, potential_impact),
                )
                return str(cur.fetchone()["id"])

    def list_opportunities(self, min_score: int = 0, status: str = "") -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                filters, params = ["score >= %s"], [min_score]
                if status:
                    filters.append("status = %s")
                    params.append(status)
                where = "WHERE " + " AND ".join(filters)
                cur.execute(
                    f"SELECT * FROM opportunities {where} ORDER BY score DESC, detected_at DESC",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]
