"""
Google Business Profile review poller and responder.

Uses the existing GoogleBusinessProfileConnector.
Star ratings arrive as strings (FIVE, FOUR, THREE, TWO, ONE) and are normalised
to integers before storage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agents.integrations.connectors.google_business_profile import GoogleBusinessProfileConnector
from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)

_STAR_MAP = {"FIVE": 5, "FOUR": 4, "THREE": 3, "TWO": 2, "ONE": 1}

_BUSINESS_CREDS: dict[str, dict[str, str]] = {
    "trusted_plumbing": {
        "account_name":  "TRUSTED_PLUMBING_GBP_ACCOUNT",
        "location_name": "TRUSTED_PLUMBING_GBP_LOCATION",
    },
}


def _creds(business: str) -> tuple[str, str]:
    mapping = _BUSINESS_CREDS.get(business)
    if not mapping:
        raise ValueError(f"No GBP credentials configured for business: {business}")
    account = getattr(settings, mapping["account_name"], "")
    location = getattr(settings, mapping["location_name"], "")
    if not account or not location:
        raise ValueError(
            f"GBP account/location env vars not set for {business}: "
            f"{mapping['account_name']}, {mapping['location_name']}"
        )
    return account, location


class GBPReviews:

    def poll(self, business: str, page_size: int = 50) -> list[dict[str, Any]]:
        """Return a list of normalised review dicts from GBP."""
        account_name, location_name = _creds(business)
        gbp = GoogleBusinessProfileConnector(called_by="reviews", method_name="list_reviews")
        raw = gbp.list_reviews(account_name, location_name, page_size=page_size)

        reviews: list[dict[str, Any]] = []
        for r in raw:
            rating = _STAR_MAP.get(r.get("starRating", ""), 0)
            if not rating:
                continue

            reviewer = r.get("reviewer", {})
            has_photo = bool(reviewer.get("profilePhotoUrl"))

            try:
                posted_at = datetime.fromisoformat(
                    r["createTime"].replace("Z", "+00:00")
                )
            except (KeyError, ValueError):
                posted_at = datetime.now(timezone.utc)

            # platform_ref stores data needed to post a reply
            review_name = r.get("name", "")
            platform_ref = {
                "review_name": review_name,
                "account_name": account_name,
                "location_name": location_name,
            }

            reviews.append(
                {
                    "platform": "google",
                    "external_id": r.get("reviewId") or review_name,
                    "reviewer_name": reviewer.get("displayName", ""),
                    "reviewer_review_count": None,
                    "reviewer_has_photo": has_photo,
                    "rating": rating,
                    "review_text": r.get("comment", ""),
                    "posted_at": posted_at,
                    "business": business,
                    "platform_ref": platform_ref,
                    "already_replied": bool(r.get("reviewReply")),
                }
            )

        return reviews

    def reply(self, platform_ref: dict[str, Any], response_text: str) -> dict[str, Any]:
        """Post a reply to a GBP review. Returns the API response dict."""
        gbp = GoogleBusinessProfileConnector(called_by="reviews", method_name="reply_to_review")
        return gbp.reply_to_review(
            account_name=platform_ref["account_name"],
            location_name=platform_ref["location_name"],
            review_name=platform_ref["review_name"],
            reply_text=response_text,
        )
