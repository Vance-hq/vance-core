"""
Contact lead scorer.

Scoring model: configurable weighted sum, capped at 100.
Weights live in config.yaml under custom.scoring_weights so they can be
tuned without a code deploy.

Default weights:
  replies          30   — highest signal: they responded
  email_clicks     20
  linkedin_activity 25  — connection accepted, replied to DM
  email_opens      10
  role_fit         10   — title match against product target personas
  company_size      5   — crude proxy for deal size / urgency fit

Tiers (configurable via config.yaml custom.scoring_tiers):
  HOT  >= 70
  WARM >= 40
  COLD  < 40

Next-action recommendations by tier + last channel:
  HOT   → book_call
  WARM  → email_followup
  COLD  → linkedin_message or wait
"""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_WEIGHTS = {
    "replies": 30,
    "email_clicks": 20,
    "linkedin_activity": 25,
    "email_opens": 10,
    "role_fit": 10,
    "company_size": 5,
}

_ROLE_FIT: dict[str, list[str]] = {
    "starpio": ["owner", "manager", "operator", "director", "founder", "ceo"],
    "oneserv": ["owner", "founder", "ceo", "contractor", "technician", "foreman"],
    "localoutrank": ["owner", "founder", "manager", "marketing", "ceo", "director"],
    "trusted_plumbing": ["homeowner", "property manager", "facilities"],
}

_COMPANY_SIZE_SCORES = {
    "1-10": 8,
    "1-50": 7,
    "11-50": 7,
    "51-200": 5,
    "201-500": 3,
    "501+": 1,
    "": 3,
}


class ContactScorer:

    def __init__(self, weights: dict[str, int] | None = None, tiers: dict[str, int] | None = None) -> None:
        self._weights = weights or _DEFAULT_WEIGHTS
        self._tier_hot = (tiers or {}).get("hot", 70)
        self._tier_warm = (tiers or {}).get("warm", 40)

    def score(
        self,
        contact_id: str,
        product: str,
        role: str,
        company_size: str,
        email_opens: int,
        email_clicks: int,
        replies: int,
        linkedin_activity: int,
    ) -> dict[str, Any]:
        """
        Compute a 0-100 score, assign tier, recommend next action.
        Returns a dict ready to pass to OutreachDB.update_contact_score().
        """
        # Clamp each signal to [0, 1] before applying weights
        signals = {
            "replies": min(replies / 1, 1.0),          # 1 reply = full weight
            "email_clicks": min(email_clicks / 3, 1.0),
            "linkedin_activity": min(linkedin_activity / 2, 1.0),
            "email_opens": min(email_opens / 5, 1.0),
            "role_fit": self._role_fit_score(role, product),
            "company_size": self._company_size_score(company_size) / 10.0,
        }

        raw = sum(self._weights.get(k, 0) * v for k, v in signals.items())
        # Normalise to 100 based on maximum possible weighted sum
        max_possible = sum(self._weights.values())
        score = min(100, int(round(raw / max_possible * 100)))

        tier = self._tier(score)
        next_action = self._next_action(tier, replies, linkedin_activity)

        logger.info("contact_scored", contact_id=contact_id, score=score, tier=tier)
        return {
            "contact_id": contact_id,
            "score": score,
            "tier": tier,
            "recommended_next_action": next_action,
            "signals": {k: round(v, 2) for k, v in signals.items()},
        }

    # ------------------------------------------------------------------

    def _tier(self, score: int) -> str:
        if score >= self._tier_hot:
            return "HOT"
        if score >= self._tier_warm:
            return "WARM"
        return "COLD"

    def _next_action(self, tier: str, replies: int, linkedin_activity: int) -> str:
        if tier == "HOT":
            return "book_call"
        if tier == "WARM":
            return "email_followup"
        if linkedin_activity == 0:
            return "linkedin_connect"
        return "linkedin_message"

    @staticmethod
    def _role_fit_score(role: str, product: str) -> float:
        role_lower = (role or "").lower()
        keywords = _ROLE_FIT.get(product, [])
        return 1.0 if any(kw in role_lower for kw in keywords) else 0.3

    @staticmethod
    def _company_size_score(company_size: str) -> int:
        for key, score in _COMPANY_SIZE_SCORES.items():
            if key and key in (company_size or ""):
                return score
        return _COMPANY_SIZE_SCORES[""]
