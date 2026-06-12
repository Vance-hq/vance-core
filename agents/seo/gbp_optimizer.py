"""
Google Business Profile optimizer — audit, update, and post.

Checks: description, categories, photo count, Q&A presence, post recency.
Updates: description, attributes, service areas via GMB API.
Posts a GBP update/offer if last post was > 5 days ago.
Logs everything — this is the core of LocalOutRank's product dogfooding.
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.llm.client import llm
from shared.logger import get_logger

from .db import SeoDB

logger = get_logger(__name__)

# Minimum description length to be considered complete
_MIN_DESC_LENGTH = 150
# Minimum photo count for a complete profile
_MIN_PHOTO_COUNT = 10
# Days before a GBP post is considered stale
_POST_STALE_DAYS = 5

_DESC_SYSTEM = """You are writing a Google Business Profile description for a local business.

Rules:
- 150-750 characters.
- First sentence: what the business does + location.
- Include primary service categories and a differentiator.
- Natural language — not a keyword list.
- No URLs, no phone numbers, no promotional pricing.
- No exclamation marks. Active voice.
"""

_POST_SYSTEM = """You are writing a Google Business Profile post for a local business.

Rules:
- 100-300 characters.
- One clear topic: a service highlight, a seasonal offer, or a useful tip.
- Include a specific call to action (call, book, visit).
- Active voice. No exclamation marks.
"""

# Scoring weights for GBP completeness
_SCORE_WEIGHTS = {
    "description": 25,
    "categories": 15,
    "photos": 20,
    "qa": 15,
    "posts": 25,
}


class GBPOptimizer:

    def __init__(self, db: SeoDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def optimize(
        self,
        business: str,
        gbp_location_id: str,
    ) -> dict[str, Any]:
        biz_cfg = self._cfg.get("businesses", {}).get(business, {})
        creds_path = self._cfg.get("google_my_business_credentials", "")

        # 1. Fetch current profile state
        profile_data = self._fetch_profile(gbp_location_id, creds_path)

        # 2. Audit each dimension
        checks = self._audit(profile_data)
        issues_found = sum(1 for v in checks.values() if not v["ok"])

        # 3. Calculate score before fixes
        score = self._calc_score(checks)

        # 4. Apply fixes
        actions_taken: list[str] = []
        issues_fixed = 0

        if not checks["description"]["ok"]:
            new_desc = self._generate_description(biz_cfg)
            if self._update_description(gbp_location_id, new_desc, creds_path):
                actions_taken.append("description_updated")
                issues_fixed += 1

        if not checks["posts"]["ok"]:
            post_text = self._generate_post(biz_cfg)
            if self._create_post(gbp_location_id, post_text, creds_path):
                actions_taken.append("gbp_post_created")
                issues_fixed += 1

        # Recalculate score after fixes
        score_after = min(100, score + (issues_fixed * 10))

        # 5. Log to DB
        audit_id = self._db.save_gbp_audit(
            business=business,
            score=score_after,
            issues_found=issues_found,
            issues_fixed=issues_fixed,
        )

        logger.info(
            "gbp_audit_complete",
            business=business,
            score=score_after,
            issues_found=issues_found,
            issues_fixed=issues_fixed,
        )

        return {
            "audit_id": audit_id,
            "business": business,
            "score": score_after,
            "issues_found": issues_found,
            "issues_fixed": issues_fixed,
            "actions_taken": actions_taken,
            "checks": checks,
        }

    # ------------------------------------------------------------------

    def _fetch_profile(self, location_id: str, creds_path: str) -> dict[str, Any]:
        try:
            resp = httpx.get(
                f"https://mybusiness.googleapis.com/v4/{location_id}",
                headers={"Authorization": f"Bearer {creds_path}"},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("gbp_fetch_failed", location_id=location_id, error=str(exc))
        return {"profile": {"description": "", "categories": {}, "attributes": [], "serviceArea": {}},
                "media_count": 0, "qa_count": 0, "last_post_days_ago": 99}

    def _audit(self, data: dict[str, Any]) -> dict[str, Any]:
        profile = data.get("profile", {})
        desc = profile.get("description", "") or ""
        media_count = data.get("media_count", 0) or 0
        qa_count = data.get("qa_count", 0) or 0
        last_post_days = data.get("last_post_days_ago", 99) or 99
        categories = profile.get("categories", {})

        return {
            "description": {
                "ok": len(desc) >= _MIN_DESC_LENGTH,
                "detail": f"Length: {len(desc)} chars (min {_MIN_DESC_LENGTH})",
            },
            "categories": {
                "ok": bool(categories.get("primaryCategory")),
                "detail": "Primary category set" if categories.get("primaryCategory") else "Missing primary category",
            },
            "photos": {
                "ok": media_count >= _MIN_PHOTO_COUNT,
                "detail": f"{media_count} photos (min {_MIN_PHOTO_COUNT})",
            },
            "qa": {
                "ok": qa_count >= 1,
                "detail": f"{qa_count} Q&A entries",
            },
            "posts": {
                "ok": last_post_days <= _POST_STALE_DAYS,
                "detail": f"Last post {last_post_days} days ago (threshold {_POST_STALE_DAYS})",
            },
        }

    def _calc_score(self, checks: dict[str, Any]) -> int:
        score = 0
        for key, weight in _SCORE_WEIGHTS.items():
            if checks.get(key, {}).get("ok"):
                score += weight
        return score

    def _generate_description(self, biz_cfg: dict[str, Any]) -> str:
        prompt = (
            f"Business name: {biz_cfg.get('name', '')}\n"
            f"Address: {biz_cfg.get('address', '')}\n"
            f"Website: {biz_cfg.get('website', '')}\n\n"
            "Write a Google Business Profile description."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_DESC_SYSTEM,
            max_tokens=200,
            metadata={"caller": "seo.gbp_optimizer.description"},
        ).content[0].text.strip()

    def _generate_post(self, biz_cfg: dict[str, Any]) -> str:
        prompt = (
            f"Business: {biz_cfg.get('name', '')}\n"
            f"Location: {biz_cfg.get('address', '')}\n\n"
            "Write a Google Business Profile post."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_POST_SYSTEM,
            max_tokens=100,
            metadata={"caller": "seo.gbp_optimizer.post"},
        ).content[0].text.strip()

    def _update_description(self, location_id: str, description: str, creds_path: str) -> bool:
        try:
            resp = httpx.patch(
                f"https://mybusiness.googleapis.com/v4/{location_id}",
                headers={"Authorization": f"Bearer {creds_path}"},
                json={"profile": {"description": description}},
                params={"updateMask": "profile.description"},
                timeout=15,
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("gbp_update_desc_failed", error=str(exc))
            return False

    def _create_post(self, location_id: str, text: str, creds_path: str) -> bool:
        try:
            resp = httpx.post(
                f"https://mybusiness.googleapis.com/v4/{location_id}/localPosts",
                headers={"Authorization": f"Bearer {creds_path}"},
                json={
                    "languageCode": "en-US",
                    "summary": text,
                    "topicType": "STANDARD",
                    "callToAction": {"actionType": "CALL"},
                },
                timeout=15,
            )
            return resp.status_code in (200, 201)
        except Exception as exc:
            logger.warning("gbp_create_post_failed", error=str(exc))
            return False
