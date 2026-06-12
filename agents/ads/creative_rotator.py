"""
Creative rotator — detect creative fatigue and run A/B tests.

Triggers:
  CTR drops > 20% week-over-week
  Meta frequency > 3.0

Flow:
  1. Check running A/B tests first — resolve any with >= 500 impressions
  2. Check fatigue signals on active campaigns
  3. Generate new variants, create creative_test record
  4. Forward image prompts to content agent (Meta only)
"""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .creative_gen import CreativeGenerator
from .db import AdsDB

logger = get_logger(__name__)

_AB_MIN_IMPRESSIONS = 500


class CreativeRotator:

    def __init__(self, db: AdsDB, gen: CreativeGenerator, cfg: dict[str, Any]) -> None:
        self._db = db
        self._gen = gen
        self._cfg = cfg
        self._queue = TaskQueue()
        self._ctr_threshold = float(cfg.get("ctr_drop_threshold", 0.20))
        self._freq_threshold = float(cfg.get("frequency_threshold", 3.0))
        self._ab_min = int(cfg.get("ab_min_impressions", _AB_MIN_IMPRESSIONS))

    def run(self, campaign_id: str | None = None) -> dict[str, Any]:
        campaigns = (
            [self._db.get_campaign(campaign_id)]
            if campaign_id
            else self._db.get_active_campaigns()
        )
        campaigns = [c for c in campaigns if c]

        resolved = 0
        rotated = 0

        for campaign in campaigns:
            cid = str(campaign["id"])

            # Step 1: resolve any completed A/B tests
            resolved += self._resolve_tests(cid)

            # Step 2: check if rotation is needed
            should_rotate, reason = self._needs_rotation(campaign)
            if should_rotate:
                result = self._rotate(campaign, reason)
                if result.get("rotated"):
                    rotated += 1

        return {"campaigns_checked": len(campaigns), "tests_resolved": resolved, "rotations": rotated}

    # ------------------------------------------------------------------

    def _resolve_tests(self, campaign_id: str) -> int:
        tests = self._db.get_running_tests(campaign_id)
        resolved = 0
        for test in tests:
            imp_a = int(test.get("impressions_a") or 0)
            imp_b = int(test.get("impressions_b") or 0)
            if imp_a < self._ab_min or imp_b < self._ab_min:
                continue

            clicks_a = int(test.get("clicks_a") or 0)
            clicks_b = int(test.get("clicks_b") or 0)
            ctr_a = clicks_a / imp_a if imp_a > 0 else 0.0
            ctr_b = clicks_b / imp_b if imp_b > 0 else 0.0

            winner = "a" if ctr_a >= ctr_b else "b"
            self._db.resolve_test(str(test["id"]), winner)
            logger.info(
                "ab_test_resolved",
                test_id=test["id"],
                winner=winner,
                ctr_a=f"{ctr_a:.4f}",
                ctr_b=f"{ctr_b:.4f}",
            )
            resolved += 1
        return resolved

    def _needs_rotation(self, campaign: dict[str, Any]) -> tuple[bool, str]:
        cid = str(campaign["id"])
        perf = self._db.get_recent_performance(cid, days=14)
        if len(perf) < 7:
            return False, ""

        # Split into this week vs last week
        this_week = perf[:7]
        last_week = perf[7:14]

        avg_ctr_this = self._avg(this_week, "ctr")
        avg_ctr_last = self._avg(last_week, "ctr")

        if avg_ctr_last and avg_ctr_this is not None:
            drop = (avg_ctr_last - avg_ctr_this) / avg_ctr_last
            if drop > self._ctr_threshold:
                return True, f"CTR dropped {drop * 100:.1f}% WoW ({avg_ctr_last:.4f} → {avg_ctr_this:.4f})"

        # Meta frequency check
        if campaign.get("platform") == "meta":
            avg_freq = self._avg(this_week, "frequency")
            if avg_freq and avg_freq > self._freq_threshold:
                return True, f"Meta frequency {avg_freq:.1f} > {self._freq_threshold}"

        return False, ""

    def _rotate(self, campaign: dict[str, Any], reason: str) -> dict[str, Any]:
        cid = str(campaign["id"])

        # Get existing creative from latest performance snapshot (best-effort)
        perf = self._db.get_recent_performance(cid, days=1)
        existing_headline = campaign.get("name", "")
        existing_description = ""

        new_creative = self._gen.generate_for_rotation(
            product=campaign["product"],
            platform=campaign["platform"],
            existing_headline=existing_headline,
            existing_description=existing_description,
            weak_signal=reason,
        )

        headline_a = existing_headline
        headline_b = new_creative["headlines"][0] if new_creative["headlines"] else existing_headline
        description_b = new_creative["descriptions"][0] if new_creative["descriptions"] else ""

        test_id = self._db.create_creative_test(
            campaign_id=cid,
            variant_a=headline_a,
            variant_b=f"{headline_b} | {description_b}",
        )

        # Forward image prompts to content agent (Meta)
        if campaign["platform"] == "meta" and new_creative.get("image_prompts"):
            for prompt in new_creative["image_prompts"][:2]:
                self._queue.push(
                    agent="content",
                    payload={
                        "action": "generate_image",
                        "prompt": prompt,
                        "context": {
                            "campaign_id": cid,
                            "test_id": test_id,
                            "purpose": "creative_rotation",
                        },
                    },
                )

        logger.info("creative_rotated", campaign_id=cid, test_id=test_id, reason=reason)
        return {"rotated": True, "test_id": test_id, "reason": reason}

    @staticmethod
    def _avg(rows: list[dict[str, Any]], field: str) -> float | None:
        vals = [float(r[field]) for r in rows if r.get(field) is not None]
        return sum(vals) / len(vals) if vals else None
