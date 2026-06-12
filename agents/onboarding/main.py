"""
Onboarding agent — drives new user activation from signup to first value.

Actions:
  new_signup_flow     — send welcome email, create checklist, schedule check-ins
  activation_nudge    — push stuck users to their next milestone
  first_value_moment  — celebrate first milestone hit, trigger NPS at 30 days
  stuck_user_alert    — detect 5+ day inactive users, send personal email from Dutch
  onboarding_audit    — weekly funnel review, LLM proposes fix, enqueues to content/dev
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .activation_nudge import ActivationNudge
from .audit import OnboardingAudit
from .db import OnboardingDB
from .first_value import FirstValueMoment
from .signup_flow import SignupFlow
from .stuck_user import StuckUserAlert

logger = get_logger(__name__)


class OnboardingAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = OnboardingDB()
        self._signup_flow = SignupFlow(self._db, cfg)
        self._nudge = ActivationNudge(self._db, cfg)
        self._first_value = FirstValueMoment(self._db, cfg)
        self._stuck_alert = StuckUserAlert(self._db, cfg)
        self._audit = OnboardingAudit(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "new_signup_flow":    lambda: self._handle_signup(p),
            "activation_nudge":   lambda: self._handle_nudge(p),
            "first_value_moment": lambda: self._handle_first_value(p),
            "stuck_user_alert":   lambda: self._handle_stuck(p),
            "onboarding_audit":   lambda: self._handle_audit(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown onboarding action: {action}"},
            )

        logger.info("onboarding_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_stuck_users(days_inactive=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # new_signup_flow
    # ------------------------------------------------------------------

    def _handle_signup(self, p: dict[str, Any]) -> dict[str, Any]:
        user_id = p.get("user_id", "")
        user_email = p.get("user_email", "")
        product = p.get("product", "")
        if not all([user_id, user_email, product]):
            return {"error": "user_id, user_email, product required"}
        return self._signup_flow.trigger(user_id=user_id, user_email=user_email, product=product)

    # ------------------------------------------------------------------
    # activation_nudge
    # ------------------------------------------------------------------

    def _handle_nudge(self, p: dict[str, Any]) -> dict[str, Any]:
        user_id = p.get("user_id", "")
        user_email = p.get("user_email", "")
        product = p.get("product", "")
        if not all([user_id, user_email, product]):
            return {"error": "user_id, user_email, product required"}
        return self._nudge.check(user_id=user_id, user_email=user_email, product=product)

    # ------------------------------------------------------------------
    # first_value_moment
    # ------------------------------------------------------------------

    def _handle_first_value(self, p: dict[str, Any]) -> dict[str, Any]:
        user_id = p.get("user_id", "")
        user_email = p.get("user_email", "")
        product = p.get("product", "")
        milestone = p.get("milestone", "")
        days_since_signup = int(p.get("days_since_signup", 0))
        if not all([user_id, user_email, product, milestone]):
            return {"error": "user_id, user_email, product, milestone required"}
        return self._first_value.celebrate(
            user_id=user_id,
            user_email=user_email,
            product=product,
            milestone=milestone,
            days_since_signup=days_since_signup,
        )

    # ------------------------------------------------------------------
    # stuck_user_alert
    # ------------------------------------------------------------------

    def _handle_stuck(self, p: dict[str, Any]) -> dict[str, Any]:
        user_lookup = p.get("user_lookup", {})
        days_inactive = int(p.get("days_inactive", 5))
        return self._stuck_alert.detect_and_alert(
            user_lookup=user_lookup,
            days_inactive=days_inactive,
        )

    # ------------------------------------------------------------------
    # onboarding_audit
    # ------------------------------------------------------------------

    def _handle_audit(self, p: dict[str, Any]) -> dict[str, Any]:
        product = p.get("product", "")
        if not product:
            return {"error": "product required"}
        return self._audit.run(product=product)


if __name__ == "__main__":
    config = AgentConfig.load("onboarding")
    OnboardingAgent("onboarding", config).run()
