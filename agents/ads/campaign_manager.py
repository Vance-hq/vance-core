"""
Campaign manager — creates and controls campaigns on Google Ads and Meta.

Conversion tracking is enforced before any launch.
Google: requires `google_conversion_action` set in config.
Meta:   requires `meta_pixel_id` set in config.
"""

from __future__ import annotations

from typing import Any

from agents.integrations.connectors.google_ads import GoogleAdsConnector
from agents.integrations.connectors.meta_ads import MetaAdsConnector
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import AdsDB

logger = get_logger(__name__)

_MICROS = 1_000_000  # Google Ads budget unit: micros (millionths of a dollar)
_CENTS = 100         # Meta Ads budget unit: cents


class CampaignManager:

    def __init__(self, db: AdsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._queue = TaskQueue()

    # ------------------------------------------------------------------
    # Google Ads
    # ------------------------------------------------------------------

    def launch_google(
        self,
        db_campaign_id: str,
        name: str,
        budget_daily: float,
        product: str,
        headlines: list[str],
        descriptions: list[str],
        keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        conversion_action = self._cfg.get("google_conversion_action", "")
        if not conversion_action:
            raise ValueError(
                "google_conversion_action not configured — set it in config.yaml "
                "before launching any Google Ads campaign."
            )

        google = GoogleAdsConnector(called_by="ads", method_name="launch_campaign")

        # Budget in micros
        budget_micros = int(budget_daily * _MICROS)

        # Create campaign (starts PAUSED so we can add ad group + ads first)
        resp = google.create_campaign(name=name, budget_micros=budget_micros)
        results = resp.get("results", [{}])
        campaign_resource = results[0].get("resourceName", "") if results else ""
        budget_resource = resp.get("results", [{}])[0].get("campaignBudget", "") if results else ""

        # Ad group
        ag_resp = google.create_ad_group(
            campaign_resource_name=campaign_resource,
            name=f"{name} — Ad Group 1",
        )
        ag_results = ag_resp.get("results", [{}])
        ad_group_resource = ag_results[0].get("resourceName", "") if ag_results else ""

        # Keywords
        if keywords and ad_group_resource:
            google.add_keywords(ad_group_resource, keywords[:20])

        # Store platform IDs in DB
        self._db.update_campaign_platform_ids(
            campaign_id=db_campaign_id,
            platform_campaign_id=campaign_resource,
            platform_budget_resource=budget_resource,
        )

        logger.info(
            "google_campaign_created",
            db_id=db_campaign_id,
            campaign_resource=campaign_resource,
        )
        return {
            "platform": "google",
            "campaign_resource": campaign_resource,
            "ad_group_resource": ad_group_resource,
            "budget_micros": budget_micros,
        }

    # ------------------------------------------------------------------
    # Meta Ads
    # ------------------------------------------------------------------

    def launch_meta(
        self,
        db_campaign_id: str,
        name: str,
        budget_daily: float,
        objective: str,
        targeting: dict[str, Any],
        headlines: list[str],
        descriptions: list[str],
        image_prompts: list[str] | None = None,
    ) -> dict[str, Any]:
        pixel_id = self._cfg.get("meta_pixel_id", "")
        if not pixel_id:
            raise ValueError(
                "meta_pixel_id not configured — set it in config.yaml "
                "before launching any Meta campaign."
            )

        meta = MetaAdsConnector(called_by="ads", method_name="launch_campaign")

        # Meta objective mapping
        _OBJECTIVE_MAP = {
            "conversions": "OUTCOME_LEADS",
            "traffic": "OUTCOME_TRAFFIC",
            "awareness": "OUTCOME_AWARENESS",
            "leads": "OUTCOME_LEADS",
        }
        meta_objective = _OBJECTIVE_MAP.get(objective.lower(), "OUTCOME_LEADS")

        campaign_resp = meta.create_campaign(name=name, objective=meta_objective)
        campaign_id = campaign_resp.get("id", "")

        # Daily budget in cents
        daily_budget_cents = int(budget_daily * _CENTS)

        targeting_with_pixel = {**targeting, "pixel_id": pixel_id}
        ad_set_resp = meta.create_ad_set(
            campaign_id=campaign_id,
            name=f"{name} — Ad Set 1",
            daily_budget_cents=daily_budget_cents,
            billing_event="IMPRESSIONS",
            optimization_goal="LEAD_GENERATION",
            targeting=targeting_with_pixel,
        )
        ad_set_id = ad_set_resp.get("id", "")

        self._db.update_campaign_platform_ids(
            campaign_id=db_campaign_id,
            platform_campaign_id=campaign_id,
            platform_ad_set_id=ad_set_id,
        )

        # If there are image prompts, forward to content agent for generation
        if image_prompts:
            for prompt in image_prompts[:3]:
                self._queue.push(
                    agent="content",
                    payload={
                        "action": "generate_image",
                        "prompt": prompt,
                        "context": {"campaign_id": db_campaign_id, "purpose": "meta_ad"},
                    },
                )

        logger.info(
            "meta_campaign_created",
            db_id=db_campaign_id,
            campaign_id=campaign_id,
            ad_set_id=ad_set_id,
        )
        return {
            "platform": "meta",
            "campaign_id": campaign_id,
            "ad_set_id": ad_set_id,
            "daily_budget_cents": daily_budget_cents,
        }

    # ------------------------------------------------------------------
    # Shared controls
    # ------------------------------------------------------------------

    def pause(self, campaign: dict[str, Any]) -> dict[str, Any]:
        platform = campaign["platform"]
        platform_id = campaign.get("platform_campaign_id", "")

        if not platform_id:
            return {"skipped": True, "reason": "no_platform_campaign_id"}

        try:
            if platform == "google":
                GoogleAdsConnector(
                    called_by="ads", method_name="pause_campaign"
                ).pause_campaign(platform_id)
            else:
                MetaAdsConnector(
                    called_by="ads", method_name="pause_campaign"
                ).pause_campaign(platform_id)
        except Exception as exc:
            logger.error("pause_failed", campaign_id=campaign["id"], error=str(exc))
            return {"paused": False, "error": str(exc)}

        self._db.update_campaign_status(campaign["id"], "paused")
        logger.info("campaign_paused", campaign_id=campaign["id"], platform=platform)
        return {"paused": True, "campaign_id": campaign["id"]}

    def update_budget(
        self, campaign: dict[str, Any], new_budget: float
    ) -> dict[str, Any]:
        min_budget = float(self._cfg.get("min_daily_budget", 5.0))
        new_budget = max(new_budget, min_budget)

        platform = campaign["platform"]
        old_budget = float(campaign.get("budget_daily", 0))

        try:
            if platform == "google":
                budget_resource = campaign.get("platform_budget_resource", "")
                if budget_resource:
                    GoogleAdsConnector(
                        called_by="ads", method_name="update_budget"
                    ).update_budget(budget_resource, int(new_budget * _MICROS))
            else:
                # Meta: update the ad set budget
                ad_set_id = campaign.get("platform_ad_set_id", "")
                if ad_set_id:
                    meta = MetaAdsConnector(called_by="ads", method_name="update_budget")
                    meta.request(
                        "POST",
                        f"https://graph.facebook.com/v19.0/{ad_set_id}",
                        params={"access_token": meta._token},
                        json={"daily_budget": int(new_budget * _CENTS)},
                    )
        except Exception as exc:
            logger.error("budget_update_failed", campaign_id=campaign["id"], error=str(exc))
            return {"updated": False, "error": str(exc)}

        self._db.update_campaign_budget(campaign["id"], new_budget)
        self._db.log_budget_change(
            campaign_id=campaign["id"],
            old_budget=old_budget,
            new_budget=new_budget,
            reason="budget_update",
        )
        return {"updated": True, "old_budget": old_budget, "new_budget": new_budget}
