"""FeatureTracker — weekly feature adoption tracking and cross-agent surfacing."""

from __future__ import annotations

from datetime import date
from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import AnalyticsDB

logger = get_logger(__name__)

_LOW_ADOPTION_THRESHOLD = 0.05


def _week_label(d: date | None = None) -> str:
    d = d or date.today()
    return f"{d.year}-W{d.isocalendar()[1]:02d}"


def _enqueue_research(product: str, unused: list[str], high_engagement: list[str]) -> None:
    try:
        TaskQueue().push(
            agent="research",
            payload={
                "action": "feature_gap_analysis",
                "product": product,
                "unused_features": unused,
                "high_engagement_features": high_engagement,
                "source": "analytics",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_research_failed", error=str(exc))


def _enqueue_onboarding(product: str, unused: list[str]) -> None:
    try:
        TaskQueue().push(
            agent="onboarding",
            payload={
                "action": "feature_nudge",
                "product": product,
                "unused_features": unused,
                "source": "analytics",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_onboarding_failed", error=str(exc))


class FeatureTracker:

    def __init__(self, db: AnalyticsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str, week: str | None = None) -> dict[str, Any]:
        current_week = week or _week_label()
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        features = prod_cfg.get("features", [])

        if not features:
            return {"product": product, "week": current_week, "features": [], "message": "no features configured"}

        active_users = self._get_active_user_count(product)
        rows = self._collect_feature_events(product, features, current_week, active_users)

        for r in rows:
            self._db.upsert_feature_usage(
                product=product,
                feature_name=r["feature_name"],
                week=current_week,
                unique_users=r["unique_users"],
                total_events=r["total_events"],
                adoption_pct=r["adoption_pct"],
            )

        unused = [r["feature_name"] for r in rows if (r["adoption_pct"] or 0) < _LOW_ADOPTION_THRESHOLD]
        high_engagement = [r["feature_name"] for r in rows if (r["adoption_pct"] or 0) >= 0.5]

        if unused or high_engagement:
            _enqueue_research(product=product, unused=unused, high_engagement=high_engagement)
        if unused:
            _enqueue_onboarding(product=product, unused=unused)

        logger.info("feature_usage_tracked", product=product, week=current_week, features=len(rows))
        return {
            "product": product,
            "week": current_week,
            "active_users": active_users,
            "features": rows,
            "unused_features": unused,
            "high_engagement_features": high_engagement,
        }

    def _get_active_user_count(self, product: str) -> int:
        try:
            from shared.db.client import get_db
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(DISTINCT user_id)::int
                        FROM user_activity
                        WHERE product = %s AND last_active_at >= CURRENT_DATE - 7
                        """,
                        (product,),
                    )
                    return cur.fetchone()[0] or 0
        except Exception as exc:
            logger.warning("active_user_count_failed", error=str(exc))
            return 0

    def _collect_feature_events(
        self,
        product: str,
        features: list[dict[str, str]],
        week: str,
        active_users: int,
    ) -> list[dict[str, Any]]:
        rows = []
        try:
            from shared.db.client import get_db
            with get_db() as conn:
                with conn.cursor() as cur:
                    for feat in features:
                        event_name = feat.get("event_name") or feat if isinstance(feat, str) else feat.get("name", "")
                        cur.execute(
                            """
                            SELECT COUNT(DISTINCT user_id)::int AS unique_users,
                                   COUNT(*)::int               AS total_events
                            FROM product_events
                            WHERE product = %s
                              AND event_name = %s
                              AND DATE_TRUNC('week', created_at) = DATE_TRUNC('week', CURRENT_DATE)
                            """,
                            (product, event_name),
                        )
                        row = cur.fetchone()
                        unique = row[0] or 0
                        total = row[1] or 0
                        adoption = round(unique / active_users, 4) if active_users > 0 else None
                        rows.append({
                            "feature_name": event_name,
                            "unique_users": unique,
                            "total_events": total,
                            "adoption_pct": adoption,
                        })
        except Exception as exc:
            logger.warning("feature_event_query_failed", error=str(exc))
        return rows
