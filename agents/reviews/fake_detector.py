"""
Fake review detector — heuristic + LLM scoring.

Signals scored and summed:
  1. reviewer_review_count < 3 (or None)         → 0.35
  2. reviewer has no profile photo                → 0.20
  3. review text is very short (< 15 chars)       → 0.15
  4. review text contains generic boilerplate     → 0.20
  5. reviewer name looks like a random handle     → 0.10

Total confidence is clamped to [0.0, 1.0].
Threshold for auto-flagging: configurable (default 0.8).
"""

from __future__ import annotations

import re
from typing import Any

from shared.logger import get_logger

logger = get_logger(__name__)

_BOILERPLATE_PATTERNS = [
    r"\bgreat service\b",
    r"\bhighly recommend\b",
    r"\bwould recommend\b",
    r"\bvery professional\b",
    r"\bfive stars\b",
    r"\b5 stars\b",
    r"\bexcellent work\b",
    r"\bgreat job\b",
    r"\bthank you\b",
    r"\bawesome\b",
]

_COMPILED_BOILERPLATE = [re.compile(p, re.IGNORECASE) for p in _BOILERPLATE_PATTERNS]

# Looks like "user123456789" or "reviewer_abc"
_GENERIC_NAME_RE = re.compile(r"^(user|reviewer|customer|guest)\d+", re.IGNORECASE)


class FakeReviewDetector:

    def score(self, review: dict[str, Any]) -> tuple[float, list[str]]:
        """
        Returns (confidence, reasons).
        confidence is in [0.0, 1.0] — higher means more likely fake.
        """
        confidence = 0.0
        reasons: list[str] = []

        # Signal 1: very few or no prior reviews from this reviewer
        review_count = review.get("reviewer_review_count")
        if review_count is None or review_count < 3:
            confidence += 0.35
            reasons.append(
                f"reviewer_count_low({review_count!r})"
            )

        # Signal 2: no profile photo
        if not review.get("reviewer_has_photo"):
            confidence += 0.20
            reasons.append("no_profile_photo")

        text = (review.get("review_text") or "").strip()

        # Signal 3: very short text
        if len(text) < 15:
            confidence += 0.15
            reasons.append(f"text_too_short({len(text)} chars)")

        # Signal 4: boilerplate phrases — count matches, cap contribution
        matches = sum(1 for p in _COMPILED_BOILERPLATE if p.search(text))
        if matches >= 2:
            confidence += min(0.20, matches * 0.05)
            reasons.append(f"generic_phrases({matches} matches)")

        # Signal 5: generic reviewer name pattern
        name = (review.get("reviewer_name") or "").strip()
        if _GENERIC_NAME_RE.match(name):
            confidence += 0.10
            reasons.append("generic_reviewer_name")

        confidence = min(1.0, confidence)
        return confidence, reasons

    def should_flag(self, confidence: float, threshold: float = 0.8) -> bool:
        return confidence >= threshold
