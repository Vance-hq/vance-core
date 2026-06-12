"""
Yelp Fusion API review poller.

Yelp Fusion returns up to 3 review excerpts per business for non-partner
API keys. Full review access requires the Yelp Business Suite partner API.
Review responses cannot be posted via the Fusion API — responses require
the private Business Suite API or the Yelp for Business portal.

Polling is implemented; posting logs the response as 'manual_post_required'.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://api.yelp.com/v3"

_BUSINESS_IDS: dict[str, str] = {
    "trusted_plumbing": "TRUSTED_PLUMBING_YELP_BUSINESS_ID",
}


def _business_id(business: str) -> str:
    env_key = _BUSINESS_IDS.get(business)
    if not env_key:
        raise ValueError(f"No Yelp business ID configured for: {business}")
    val = getattr(settings, env_key, "")
    if not val:
        raise ValueError(f"Yelp business ID env var not set: {env_key}")
    return val


class YelpReviews:

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.YELP_API_KEY}"}

    def poll(self, business: str) -> list[dict[str, Any]]:
        """Return up to 3 Yelp review excerpts (Fusion API limit)."""
        if not settings.YELP_API_KEY:
            logger.warning("yelp_poll_skipped", reason="YELP_API_KEY not configured")
            return []

        biz_id = _business_id(business)
        try:
            resp = httpx.get(
                f"{_BASE}/businesses/{biz_id}/reviews",
                headers=self._headers(),
                timeout=20.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("yelp_poll_failed", business=business, error=str(exc))
            return []

        reviews: list[dict[str, Any]] = []
        for r in data.get("reviews", []):
            try:
                posted_at = datetime.fromisoformat(
                    r["time_created"].replace(" ", "T") + "+00:00"
                    if "+" not in r["time_created"]
                    else r["time_created"]
                )
            except (KeyError, ValueError):
                posted_at = datetime.now(timezone.utc)

            user = r.get("user", {})
            has_photo = bool(user.get("image_url"))

            reviews.append(
                {
                    "platform": "yelp",
                    "external_id": r.get("id", ""),
                    "reviewer_name": user.get("name", ""),
                    "reviewer_review_count": user.get("review_count"),
                    "reviewer_has_photo": has_photo,
                    "rating": int(r.get("rating", 0)),
                    "review_text": r.get("text", ""),
                    "posted_at": posted_at,
                    "business": business,
                    "platform_ref": {"yelp_review_id": r.get("id", ""), "yelp_url": r.get("url", "")},
                    "already_replied": False,
                }
            )

        return reviews

    def reply(self, platform_ref: dict[str, Any], response_text: str) -> dict[str, Any]:
        """Yelp Fusion does not support posting review responses programmatically."""
        logger.info(
            "yelp_reply_manual_required",
            yelp_url=platform_ref.get("yelp_url"),
        )
        return {"outcome": "manual_post_required", "url": platform_ref.get("yelp_url", "")}
