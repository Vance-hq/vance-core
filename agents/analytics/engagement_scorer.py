"""EngagementScorer — per-user scoring and tiering with cross-agent dispatch."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import AnalyticsDB

logger = get_logger(__name__)

# Tier thresholds (top percentile or score cutoffs)
_POWER_USER_PERCENTILE = 0.10
_AT_RISK_DAYS = 7
_DORMANT_DAYS = 14

_DEFAULT_WEIGHTS = {
    "login_frequency": 0.30,
    "feature_breadth": 0.25,
    "session_duration": 0.25,
    "recency": 0.20,
}


def _enqueue_churn_recovery(product: str, user_ids: list[str]) -> None:
    try:
        TaskQueue().push(
            agent="sales",
            payload={"action": "churn_recovery", "product": product, "user_ids": user_ids, "source": "analytics"},
        )
    except Exception as exc:
        logger.warning("enqueue_churn_recovery_failed", error=str(exc))


def _enqueue_stuck_user_alert(product: str, user_ids: list[str]) -> None:
    try:
        TaskQueue().push(
            agent="onboarding",
            payload={"action": "stuck_user_alert", "product": product, "user_ids": user_ids, "source": "analytics"},
        )
    except Exception as exc:
        logger.warning("enqueue_stuck_user_alert_failed", error=str(exc))


def _compute_score(user: dict[str, Any], weights: dict[str, float]) -> float:
    """0–100 score based on weighted components."""
    login_score = min(user.get("logins_last_7d", 0) / 7.0, 1.0)
    breadth_score = min(user.get("features_used", 0) / max(user.get("total_features", 1), 1), 1.0)
    # session_duration_score: normalize against 60 min cap
    session_score = min(user.get("avg_session_minutes", 0) / 60.0, 1.0)
    days_inactive = user.get("days_since_last_active", 0)
    recency_score = max(0.0, 1.0 - (days_inactive / 30.0))

    raw = (
        weights.get("login_frequency", 0.30) * login_score
        + weights.get("feature_breadth", 0.25) * breadth_score
        + weights.get("session_duration", 0.25) * session_score
        + weights.get("recency", 0.20) * recency_score
    )
    return round(raw * 100, 2)


def _assign_tier(
    score: float,
    days_inactive: int,
    power_threshold: float,
    at_risk_days: int,
    dormant_days: int,
) -> str:
    if days_inactive >= dormant_days:
        return "DORMANT"
    if days_inactive >= at_risk_days:
        return "AT_RISK"
    if score >= power_threshold:
        return "POWER_USER"
    return "ACTIVE"


class EngagementScorer:

    def __init__(self, db: AnalyticsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        weights = self._cfg.get("engagement_weights", _DEFAULT_WEIGHTS)
        at_risk_days = int(self._cfg.get("at_risk_days", _AT_RISK_DAYS))
        dormant_days = int(self._cfg.get("dormant_days", _DORMANT_DAYS))

        users = self._load_user_activity(product)
        if not users:
            return {"product": product, "users_scored": 0, "tier_counts": {}}

        scores = [(u, _compute_score(u, weights)) for u in users]
        sorted_scores = sorted(scores, key=lambda x: x[1], reverse=True)
        power_cutoff_idx = max(1, int(len(sorted_scores) * _POWER_USER_PERCENTILE))
        power_threshold = sorted_scores[power_cutoff_idx - 1][1] if sorted_scores else 100.0

        at_risk_ids: list[str] = []
        dormant_ids: list[str] = []

        for user, score in scores:
            days_inactive = user.get("days_since_last_active", 0)
            tier = _assign_tier(score, days_inactive, power_threshold, at_risk_days, dormant_days)
            self._db.upsert_engagement_score(
                user_id=user["user_id"],
                product=product,
                score=score,
                tier=tier,
            )
            if tier == "AT_RISK":
                at_risk_ids.append(user["user_id"])
            elif tier == "DORMANT":
                dormant_ids.append(user["user_id"])

        if at_risk_ids:
            _enqueue_churn_recovery(product=product, user_ids=at_risk_ids)
        if dormant_ids:
            _enqueue_stuck_user_alert(product=product, user_ids=dormant_ids)

        tier_counts = self._db.get_tier_counts(product=product)
        logger.info("engagement_scored", product=product, users=len(users), tier_counts=tier_counts)
        return {
            "product": product,
            "users_scored": len(users),
            "at_risk_dispatched": len(at_risk_ids),
            "dormant_dispatched": len(dormant_ids),
            "tier_counts": tier_counts,
        }

    def _load_user_activity(self, product: str) -> list[dict[str, Any]]:
        try:
            from shared.db.client import get_db
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            user_id,
                            COUNT(DISTINCT DATE(created_at))
                                FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS logins_last_7d,
                            COUNT(DISTINCT event_name) AS features_used,
                            COALESCE(AVG(session_minutes), 0) AS avg_session_minutes,
                            (CURRENT_DATE - MAX(created_at)::date) AS days_since_last_active
                        FROM product_events
                        WHERE product = %s
                        GROUP BY user_id
                        """,
                        (product,),
                    )
                    cols = ["user_id", "logins_last_7d", "features_used",
                            "avg_session_minutes", "days_since_last_active"]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning("load_user_activity_failed", error=str(exc))
            return []
