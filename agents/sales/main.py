"""
Sales agent — conversion funnel: trial activation, upgrades, churn, win-back, referrals.

Actions:
  trial_nudge      — re-engage stalled trials (daily batch)
  upgrade_nudge    — nudge free/starter users hitting plan limits (daily batch)
  churn_recovery   — immediate personal email + Stripe extension on cancel event
  win_back         — 2-step re-engagement for users churned 30-90 days ago (weekly)
  referral_trigger — invite happy customers (NPS >= 8, 30+ days active) to refer
  pricing_intel    — scrape competitor pricing, alert strategy agent on changes (weekly)
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.db.client import get_db
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .churn_recovery import ChurnRecovery
from .db import SalesDB
from .mailer import SalesMailer
from .pricing_intel import PricingIntel
from .referral import ReferralTrigger
from .trial_nudge import TrialNudge
from .upgrade_nudge import UpgradeNudge
from .win_back import WinBack

logger = get_logger(__name__)


class SalesAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = SalesDB()
        self._mailer = SalesMailer()

        self._trial_nudge = TrialNudge(self._db, self._mailer, cfg)
        self._upgrade_nudge = UpgradeNudge(self._db, self._mailer, cfg)
        self._churn_recovery = ChurnRecovery(self._db, self._mailer, cfg)
        self._win_back = WinBack(self._db, self._mailer, cfg)
        self._referral = ReferralTrigger(self._db, self._mailer, cfg)
        self._pricing_intel = PricingIntel(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "trial_nudge":      lambda: self._handle_trial_nudge(p),
            "upgrade_nudge":    lambda: self._handle_upgrade_nudge(p),
            "churn_recovery":   lambda: self._handle_churn_recovery(p),
            "win_back":         lambda: self._handle_win_back(p),
            "referral_trigger": lambda: self._handle_referral(p),
            "pricing_intel":    lambda: self._handle_pricing_intel(p),
        }

        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"Unknown sales action: {action}")

        logger.info("sales_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM sales_actions LIMIT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _handle_trial_nudge(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload: none required for batch run.
        Optional: user_id (str) — run for a single user.
        """
        if user_id := p.get("user_id"):
            user = self._db.get_user(user_id)
            if not user:
                return {"error": "user_not_found"}
            # Single-user path: call run() after pre-loading only this user — delegate to batch
        return self._trial_nudge.run()

    def _handle_upgrade_nudge(self, _p: dict[str, Any]) -> dict[str, Any]:
        return self._upgrade_nudge.run()

    def _handle_churn_recovery(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required: user_id OR stripe_customer_id.
        Stripe webhook sends stripe_customer_id; manual trigger sends user_id.
        """
        user_id = p.get("user_id")
        if not user_id:
            stripe_customer_id = p.get("stripe_customer_id")
            if not stripe_customer_id:
                return {"error": "user_id or stripe_customer_id required"}
            user = self._db.get_user_by_stripe_customer(stripe_customer_id)
            if not user:
                return {"error": "user_not_found_for_stripe_customer"}
            user_id = str(user["id"])

        return self._churn_recovery.recover(user_id)

    def _handle_win_back(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Sub-actions:
          (none)    — batch run for all eligible churned users
          step2     — send the second win-back email to a specific user
        """
        sub = p.get("sub_action", "batch")
        if sub == "step2":
            user_id = p.get("user_id")
            if not user_id:
                return {"error": "user_id required for step2"}
            return self._win_back.send_step2(user_id)
        return self._win_back.run()

    def _handle_referral(self, _p: dict[str, Any]) -> dict[str, Any]:
        return self._referral.run()

    def _handle_pricing_intel(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Optional: products (list[str]) — limit to specific products.
        """
        products = p.get("products")
        return self._pricing_intel.run(products=products)


if __name__ == "__main__":
    config = AgentConfig.load("sales")
    SalesAgent("sales", config).run()
