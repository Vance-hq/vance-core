"""
Review responder — generates LLM responses and routes them to the correct platform.

Tone guidance per star rating:
  5-star  — warm, specific, invite back or ask for referral
  4-star  — thank them, address the gap, invite direct contact
  ≤3-star — acknowledge, take accountability, offer to make it right, move offline
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timezone
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

_FRAMEWORKS_MD = (
    pathlib.Path(__file__).parent.parent / "marketing" / "prompts" / "frameworks.md"
).read_text()

from .db import ReviewsDB
from .platforms.facebook import FacebookReviews
from .platforms.gbp import GBPReviews
from .platforms.yelp import YelpReviews

logger = get_logger(__name__)

_SYSTEM = (
    """Respond as the business owner. You are Dutch Munn, owner of Trusted Plumbing.
You have 26 years in the trades. You take pride in your work and stand behind it.
Never defensive. Never robotic. Always specific to what they said.
A negative review is an invitation to make it right, not an attack to deflect.
Keep responses under 120 words. End with a direct contact offer on anything below 4 stars.

Active framework_mode: review_response
Apply Kern reader-is-hero rules: the customer is always the hero. You are accountable,
not defensive. One clear message per response. Specificity beats generic apology.\n\n"""
    "## Copywriting Frameworks Reference\n\n" + _FRAMEWORKS_MD
)

_TONE_NOTES = {
    5: (
        "This is a 5-star review. Be warm and specific to what they described. "
        "Invite them back by name or ask if they know anyone else who needs help. "
        "Do NOT mention the star rating or ask them to share — that's forced."
    ),
    4: (
        "This is a 4-star review — something wasn't perfect. Thank them, then "
        "address the gap in one sentence. Invite them to call you directly to "
        "sort out whatever was missing. End with your direct line."
    ),
    3: (
        "This is a 3-star review. Acknowledge what went wrong. Don't deflect or "
        "explain away. Offer to make it right. Move the conversation offline with "
        "a specific ask to call or email you."
    ),
    2: (
        "This is a 2-star review. Take accountability. Don't justify anything. "
        "Acknowledge the specific problem they described. Offer a concrete next "
        "step to fix it. End with your direct phone number."
    ),
    1: (
        "This is a 1-star review. Take full accountability. Don't argue, don't "
        "deflect, don't say 'we're sorry you feel that way'. Address what happened "
        "specifically. Give a direct contact: phone number and name."
    ),
}


class ReviewResponder:

    def __init__(self, db: ReviewsDB) -> None:
        self._db = db
        self._gbp = GBPReviews()
        self._yelp = YelpReviews()
        self._fb = FacebookReviews()

    def respond(self, review_id: str) -> dict[str, Any]:
        review = self._db.get_review(review_id)
        if not review:
            return {"error": "review_not_found"}

        if review.get("responded_at"):
            return {"skipped": True, "reason": "already_responded"}

        rating = int(review["rating"])
        response_text = self._generate(review, rating)

        outcome = self._post(review, response_text)

        posted_at = datetime.now(timezone.utc) if outcome == "posted" else None
        self._db.log_response(review_id, response_text, posted_at, outcome)

        if outcome in ("posted", "manual_post_required"):
            self._db.mark_responded(review_id)

        logger.info(
            "review_responded",
            review_id=review_id,
            platform=review["platform"],
            rating=rating,
            outcome=outcome,
        )
        return {"review_id": review_id, "outcome": outcome, "response_preview": response_text[:80]}

    def _generate(self, review: dict[str, Any], rating: int) -> str:
        tone = _TONE_NOTES.get(rating, _TONE_NOTES[1])
        prompt = (
            f"Platform: {review['platform']}\n"
            f"Reviewer: {review['reviewer_name']}\n"
            f"Star rating: {rating}\n"
            f"Their review:\n{review['review_text']}\n\n"
            f"Tone guidance: {tone}\n\n"
            "Write the response. Output only the response text, nothing else."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            max_tokens=200,
            metadata={"caller": "reviews.responder"},
        ).content[0].text.strip()

    def _post(self, review: dict[str, Any], response_text: str) -> str:
        platform = review["platform"]
        platform_ref = dict(review.get("platform_ref") or {})

        try:
            if platform == "google":
                self._gbp.reply(platform_ref, response_text)
                return "posted"
            elif platform == "yelp":
                result = self._yelp.reply(platform_ref, response_text)
                return result.get("outcome", "manual_post_required")
            elif platform == "facebook":
                result = self._fb.reply(platform_ref, response_text)
                return result.get("outcome", "failed")
        except Exception as exc:
            logger.error(
                "review_post_failed",
                review_id=review.get("id"),
                platform=platform,
                error=str(exc),
            )
            return "failed"

        return "manual_post_required"
