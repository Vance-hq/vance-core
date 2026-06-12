"""
Ads agent — autonomous paid ad management across Google and Meta.

Actions:
  create_campaign     — generate creative, verify conversion tracking, launch
  monitor_performance — daily metrics + LLM analysis; pause on CPA breach, scale on ROAS win
  rotate_creative     — refresh fatigue-hit creatives; run A/B tests
  audience_expand     — monthly lookalike/interest expansion from customer list
  budget_realloc      — weekly ROAS-based budget rebalancing
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .audience_builder import AudienceBuilder
from .budget_reallocator import BudgetReallocator
from .campaign_manager import CampaignManager
from .creative_gen import CreativeGenerator
from .creative_rotator import CreativeRotator
from .db import AdsDB
from .performance_monitor import PerformanceMonitor

logger = get_logger(__name__)


class AdsAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = AdsDB()
        self._gen = CreativeGenerator()
        self._mgr = CampaignManager(self._db, cfg)
        self._monitor = PerformanceMonitor(self._db, self._mgr, cfg)
        self._rotator = CreativeRotator(self._db, self._gen, cfg)
        self._audience = AudienceBuilder(self._db, cfg)
        self._reallocator = BudgetReallocator(self._db, self._mgr, cfg)
        self._product_targets: dict[str, dict[str, float]] = cfg.get("product_targets", {})

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "create_campaign":     lambda: self._handle_create_campaign(p),
            "monitor_performance": lambda: self._handle_monitor(p),
            "rotate_creative":     lambda: self._handle_rotate(p),
            "audience_expand":     lambda: self._handle_audience_expand(p),
            "budget_realloc":      lambda: self._handle_budget_realloc(p),
        }

        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"Unknown ads action: {action}")

        logger.info("ads_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_active_campaigns()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # create_campaign
    # ------------------------------------------------------------------

    def _handle_create_campaign(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product        (str)  — starpio | oneserv | localoutrank | trusted_plumbing
          platform       (str)  — google | meta
          objective      (str)  — conversions | traffic | awareness | leads
          budget_daily   (float) — USD per day
          audience       (str)  — description of target audience
          creative_brief (str)  — angle / key message for creative

        Optional:
          target_cpa     (float) — override product default
          target_roas    (float) — override product default
          keywords       (list[str]) — Google only
          targeting      (dict)      — Meta only (audience targeting spec)
        """
        product = p.get("product")
        platform = p.get("platform")
        objective = p.get("objective", "conversions")
        budget_daily = float(p.get("budget_daily", 10.0))
        audience = p.get("audience", "")
        creative_brief = p.get("creative_brief", "")

        if not product or not platform:
            return {"error": "product and platform required"}
        if platform not in ("google", "meta"):
            return {"error": "platform must be 'google' or 'meta'"}

        # Defaults from product config
        defaults = self._product_targets.get(product, {})
        target_cpa = float(p.get("target_cpa") or defaults.get("target_cpa") or 0)
        target_roas = float(p.get("target_roas") or defaults.get("target_roas") or 0)

        # Generate creative
        creative = self._gen.generate(
            product=product,
            platform=platform,
            objective=objective,
            audience=audience,
            creative_brief=creative_brief,
        )

        campaign_name = f"{product} — {platform} — {objective} — {len(self._db.get_active_campaigns()) + 1}"

        # Create DB record first (before platform API so we have an ID to link)
        db_id = self._db.create_campaign(
            product=product,
            platform=platform,
            name=campaign_name,
            objective=objective,
            budget_daily=budget_daily,
            target_cpa=target_cpa if target_cpa else None,
            target_roas=target_roas if target_roas else None,
        )

        # Launch on platform
        try:
            if platform == "google":
                launch_result = self._mgr.launch_google(
                    db_campaign_id=db_id,
                    name=campaign_name,
                    budget_daily=budget_daily,
                    product=product,
                    headlines=creative["headlines"],
                    descriptions=creative["descriptions"],
                    keywords=p.get("keywords"),
                )
            else:
                launch_result = self._mgr.launch_meta(
                    db_campaign_id=db_id,
                    name=campaign_name,
                    budget_daily=budget_daily,
                    objective=objective,
                    targeting=p.get("targeting", {}),
                    headlines=creative["headlines"],
                    descriptions=creative["descriptions"],
                    image_prompts=creative.get("image_prompts"),
                )
        except ValueError as exc:
            # Conversion tracking not configured — fail safe
            self._db.update_campaign_status(db_id, "paused")
            return {"error": str(exc), "campaign_id": db_id, "status": "not_launched"}

        logger.info("campaign_created", db_id=db_id, platform=platform, product=product)
        return {
            "campaign_id": db_id,
            "platform": platform,
            "product": product,
            "budget_daily": budget_daily,
            "creative": {
                "headlines": creative["headlines"][:2],
                "descriptions": creative["descriptions"][:2],
                "ctas": creative["ctas"],
            },
            "launch": launch_result,
        }

    # ------------------------------------------------------------------
    # monitor_performance
    # ------------------------------------------------------------------

    def _handle_monitor(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Optional:
          campaign_id (str) — monitor a specific campaign; omit for all active
        """
        return self._monitor.run(campaign_id=p.get("campaign_id"))

    # ------------------------------------------------------------------
    # rotate_creative
    # ------------------------------------------------------------------

    def _handle_rotate(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Optional:
          campaign_id (str) — rotate for a specific campaign; omit for all active
        """
        return self._rotator.run(campaign_id=p.get("campaign_id"))

    # ------------------------------------------------------------------
    # audience_expand
    # ------------------------------------------------------------------

    def _handle_audience_expand(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Optional:
          campaign_id (str) — expand for a specific campaign; omit for all due
        """
        campaign_id = p.get("campaign_id")
        if campaign_id:
            return self._audience.expand(campaign_id)
        return self._audience.expand_all_due()

    # ------------------------------------------------------------------
    # budget_realloc
    # ------------------------------------------------------------------

    def _handle_budget_realloc(self, _p: dict[str, Any]) -> dict[str, Any]:
        return self._reallocator.rebalance()


if __name__ == "__main__":
    config = AgentConfig.load("ads")
    AdsAgent("ads", config).run()
