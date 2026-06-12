"""
Facebook Graph API review (ratings) poller and responder.

Endpoint: GET /{page_id}/ratings
Reply:    POST /{review_id}/comments

Requires a Page Access Token with pages_manage_engagement permission.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)

_GRAPH = "https://graph.facebook.com/v19.0"

_BUSINESS_PAGES: dict[str, str] = {
    "trusted_plumbing": "TRUSTED_PLUMBING_FACEBOOK_PAGE_ID",
}


def _page_id(business: str) -> str:
    env_key = _BUSINESS_PAGES.get(business)
    if not env_key:
        raise ValueError(f"No Facebook page ID configured for: {business}")
    val = getattr(settings, env_key, "")
    if not val:
        raise ValueError(f"Facebook page ID env var not set: {env_key}")
    return val


class FacebookReviews:

    def _token(self) -> str:
        return settings.FACEBOOK_PAGE_ACCESS_TOKEN

    def poll(self, business: str, limit: int = 25) -> list[dict[str, Any]]:
        """Return Facebook Page ratings as normalised review dicts."""
        if not self._token():
            logger.warning("facebook_poll_skipped", reason="FACEBOOK_PAGE_ACCESS_TOKEN not configured")
            return []

        page_id = _page_id(business)
        try:
            resp = httpx.get(
                f"{_GRAPH}/{page_id}/ratings",
                params={
                    "fields": "reviewer,rating,review_text,created_time,open_graph_story",
                    "limit": limit,
                    "access_token": self._token(),
                },
                timeout=20.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("facebook_poll_failed", business=business, error=str(exc))
            return []

        reviews: list[dict[str, Any]] = []
        for r in data.get("data", []):
            rating = int(r.get("rating", 0))
            if rating < 1 or rating > 5:
                continue

            try:
                posted_at = datetime.fromisoformat(
                    r["created_time"].replace("Z", "+00:00")
                )
            except (KeyError, ValueError):
                posted_at = datetime.now(timezone.utc)

            reviewer = r.get("reviewer", {})
            story = r.get("open_graph_story", {})
            story_id = story.get("id", r.get("id", ""))

            reviews.append(
                {
                    "platform": "facebook",
                    "external_id": story_id or r.get("id", ""),
                    "reviewer_name": reviewer.get("name", ""),
                    "reviewer_review_count": None,
                    "reviewer_has_photo": False,
                    "rating": rating,
                    "review_text": r.get("review_text", ""),
                    "posted_at": posted_at,
                    "business": business,
                    "platform_ref": {
                        "story_id": story_id,
                        "page_id": page_id,
                        "reviewer_id": reviewer.get("id", ""),
                    },
                    "already_replied": False,
                }
            )

        return reviews

    def reply(self, platform_ref: dict[str, Any], response_text: str) -> dict[str, Any]:
        """Post a comment reply on the Facebook rating story."""
        if not self._token():
            return {"outcome": "manual_post_required", "reason": "token_not_configured"}

        story_id = platform_ref.get("story_id", "")
        if not story_id:
            return {"outcome": "failed", "reason": "no_story_id"}

        try:
            resp = httpx.post(
                f"{_GRAPH}/{story_id}/comments",
                params={"access_token": self._token()},
                json={"message": response_text},
                timeout=20.0,
            )
            resp.raise_for_status()
            return {"outcome": "posted", "comment_id": resp.json().get("id")}
        except Exception as exc:
            logger.error("facebook_reply_failed", story_id=story_id, error=str(exc))
            return {"outcome": "failed", "error": str(exc)}
