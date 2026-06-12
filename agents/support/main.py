"""
Support agent — customer support across all products.

Actions:
  handle_ticket      — classify + respond to an inbound support ticket
  resolve_auto       — fully automated resolution (password reset, plan change, etc.)
  kb_update          — weekly KB refresh from resolved tickets
  proactive_support  — detect issues before customers complain
  nps_survey         — send surveys (sub_action=send) or record scores (sub_action=record)
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .auto_resolver import AutoResolver
from .db import SupportDB
from .kb_manager import KBManager
from .nps_manager import NpsManager
from .proactive_monitor import ProactiveMonitor
from .ticket_handler import TicketHandler

logger = get_logger(__name__)


class SupportAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = SupportDB()
        self._ticket_handler = TicketHandler(self._db, cfg)
        self._resolver = AutoResolver(self._db, cfg)
        self._kb = KBManager(self._db, cfg)
        self._monitor = ProactiveMonitor(self._db, cfg)
        self._nps = NpsManager(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "handle_ticket":     lambda: self._handle_ticket(p),
            "resolve_auto":      lambda: self._handle_resolve_auto(p),
            "kb_update":         lambda: self._handle_kb_update(p),
            "proactive_support": lambda: self._handle_proactive(p),
            "nps_survey":        lambda: self._handle_nps(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown support action: {action}"},
            )

        logger.info("support_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.list_resolved_tickets(product="localoutrank", limit=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # handle_ticket
    # ------------------------------------------------------------------

    def _handle_ticket(self, p: dict[str, Any]) -> dict[str, Any]:
        product = p.get("product", "")
        user_id = p.get("user_id", "")
        channel = p.get("channel", "email")
        subject = p.get("subject", "")
        body = p.get("body", "")
        user_email = p.get("user_email", "")
        if not all([product, user_id, subject, body, user_email]):
            return {"error": "product, user_id, subject, body, user_email required"}
        return self._ticket_handler.handle(
            product=product,
            user_id=user_id,
            channel=channel,
            subject=subject,
            body=body,
            user_email=user_email,
        )

    # ------------------------------------------------------------------
    # resolve_auto
    # ------------------------------------------------------------------

    def _handle_resolve_auto(self, p: dict[str, Any]) -> dict[str, Any]:
        auto_action = p.get("auto_action", "")
        user_id = p.get("user_id", "")
        user_email = p.get("user_email", "")
        product = p.get("product", "")
        if not all([auto_action, user_id, user_email, product]):
            return {"error": "auto_action, user_id, user_email, product required"}
        return self._resolver.resolve(
            action=auto_action,
            user_id=user_id,
            user_email=user_email,
            product=product,
            new_plan_id=p.get("new_plan_id", ""),
        )

    # ------------------------------------------------------------------
    # kb_update
    # ------------------------------------------------------------------

    def _handle_kb_update(self, p: dict[str, Any]) -> dict[str, Any]:
        product = p.get("product", "")
        if not product:
            return {"error": "product required"}
        return self._kb.update(product=product)

    # ------------------------------------------------------------------
    # proactive_support
    # ------------------------------------------------------------------

    def _handle_proactive(self, p: dict[str, Any]) -> dict[str, Any]:
        product = p.get("product", "")
        if not product:
            return {"error": "product required"}
        return self._monitor.check(product=product)

    # ------------------------------------------------------------------
    # nps_survey
    # ------------------------------------------------------------------

    def _handle_nps(self, p: dict[str, Any]) -> dict[str, Any]:
        sub_action = p.get("sub_action", "send")
        user_id = p.get("user_id", "")
        product = p.get("product", "")

        if sub_action == "send":
            user_email = p.get("user_email", "")
            if not all([user_id, user_email, product]):
                return {"error": "user_id, user_email, product required"}
            return self._nps.send_survey(user_id=user_id, user_email=user_email, product=product)

        elif sub_action == "record":
            score = p.get("score")
            if score is None or not user_id or not product:
                return {"error": "user_id, product, score required"}
            return self._nps.record(
                user_id=user_id,
                product=product,
                score=int(score),
                comment=p.get("comment", ""),
            )

        return {"error": f"Unknown nps sub_action: {sub_action}"}


if __name__ == "__main__":
    config = AgentConfig.load("support")
    SupportAgent("support", config).run()
