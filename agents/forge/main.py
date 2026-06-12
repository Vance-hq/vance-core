"""
Forge agent — autonomous cold outreach engine interface.

Actions:
  build_lead_list    — scrape + enrich targeted leads
  launch_sequence    — start Forge email sequence for a lead list
  monitor_sequence   — real-time sequence metrics + reply handling
  optimize_sequence  — A/B test analysis and variant application
  warm_domain        — manage email domain warm-up
  lead_score_forge   — score leads by engagement, escalate HOT
  forge_report       — daily performance summary
"""

from __future__ import annotations

import json
from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.db.client import get_db
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .api_client import ForgeAPIClient
from .crm import TwentyCRMClient
from .db import ForgeDB
from .monitor import SequenceMonitor
from .optimizer import SequenceOptimizer
from .reporter import ForgeReporter
from .scorer import LeadScorer
from .scraper import LeadScraper
from .sequence import SequenceLauncher
from .warmer import DomainWarmer

logger = get_logger(__name__)


class ForgeAgent(BaseAgent):
    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = ForgeDB()
        self._crm = TwentyCRMClient()
        self._forge_api = ForgeAPIClient()
        self._scraper = LeadScraper()
        self._launcher = SequenceLauncher(self._db, cfg)
        self._monitor = SequenceMonitor(self._db, cfg.get("bounce_rate_alert_threshold", 0.08))
        self._optimizer = SequenceOptimizer(self._db, cfg.get("min_sends_for_optimize", 200))
        self._scorer = LeadScorer(self._db, self._crm, cfg.get("hot_lead_threshold", 60))
        self._reporter = ForgeReporter(self._db)
        self._warm_schedule: list[int] = cfg.get("warm_up_schedule_daily", [10, 25, 50, 100])

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "build_lead_list": lambda: self._build_lead_list(p),
            "launch_sequence": lambda: self._launch_sequence(p),
            "monitor_sequence": lambda: self._monitor_sequence(p),
            "optimize_sequence": lambda: self._optimize_sequence(p),
            "warm_domain": lambda: self._warm_domain(p),
            "lead_score_forge": lambda: self._lead_score_forge(p),
            "forge_report": lambda: self._forge_report(p),
        }

        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"Unknown forge action: {action}")

        logger.info("forge_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM forge_leads LIMIT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Action: build_lead_list
    # ------------------------------------------------------------------

    def _build_lead_list(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload:
          product: str
          target_persona: {title, industry, company_size, geography}
          quantity: int
        """
        product = p["product"]
        persona = p.get("target_persona", {})
        quantity = int(p.get("quantity", 50))

        leads = self._scraper.build_lead_list(persona, quantity, product)

        stored_ids: list[str] = []
        skipped = 0
        for lead in leads:
            if lead.get("email") and self._db.lead_exists(lead["email"]):
                skipped += 1
                continue
            lead_id = self._db.upsert_lead(lead)
            stored_ids.append(lead_id)

            # Sync to Twenty CRM
            crm_id = self._crm.upsert_contact(lead)
            if crm_id:
                self._db.update_lead_crm_id(lead_id, crm_id)

        logger.info("build_lead_list_done", product=product, stored=len(stored_ids), skipped=skipped)
        return {
            "product": product,
            "persona": persona,
            "lead_ids": stored_ids,
            "stored": len(stored_ids),
            "skipped_duplicates": skipped,
            "total_scraped": len(leads),
        }

    # ------------------------------------------------------------------
    # Action: launch_sequence
    # ------------------------------------------------------------------

    def _launch_sequence(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload:
          product: str
          lead_list_id: str | list[str]   (comma-sep UUIDs or JSON array)
          sequence_template_id: str
          from_alias: str
        """
        lead_list_raw = p["lead_list_id"]
        if isinstance(lead_list_raw, list):
            lead_list_id = json.dumps(lead_list_raw)
        else:
            lead_list_id = lead_list_raw

        result = self._launcher.launch(
            lead_list_id=lead_list_id,
            sequence_id=p["sequence_template_id"],
            from_alias=p["from_alias"],
        )
        return result

    # ------------------------------------------------------------------
    # Action: monitor_sequence
    # ------------------------------------------------------------------

    def _monitor_sequence(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload:
          sequence_id: str
          reply_body: str (optional — process an inbound reply)
          send_id: str    (required if reply_body provided)
        """
        sequence_id = p["sequence_id"]

        # If an inbound reply is attached, classify and act
        if p.get("reply_body") and p.get("send_id"):
            reply_result = self._monitor.process_reply(p["send_id"], p["reply_body"])
            metrics = self._monitor.monitor(sequence_id)
            return {**metrics, "reply_processed": reply_result}

        return self._monitor.monitor(sequence_id)

    # ------------------------------------------------------------------
    # Action: optimize_sequence
    # ------------------------------------------------------------------

    def _optimize_sequence(self, p: dict[str, Any]) -> dict[str, Any]:
        return self._optimizer.optimize(p["sequence_id"])

    # ------------------------------------------------------------------
    # Action: warm_domain
    # ------------------------------------------------------------------

    def _warm_domain(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload:
          alias: str           — sender email address
          alias_password: str
          days_warmed: int     — how many calendar days this alias has been warming
        """
        warmer = DomainWarmer(schedule=self._warm_schedule)
        return warmer.warm(
            alias=p["alias"],
            alias_password=p["alias_password"],
            days_warmed=int(p.get("days_warmed", 0)),
        )

    # ------------------------------------------------------------------
    # Action: lead_score_forge
    # ------------------------------------------------------------------

    def _lead_score_forge(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Payload:
          lead_ids: list[str] (optional — scores all active leads if omitted)
        """
        lead_ids: list[str] | None = p.get("lead_ids")
        return self._scorer.score_leads(lead_ids)

    # ------------------------------------------------------------------
    # Action: forge_report
    # ------------------------------------------------------------------

    def _forge_report(self, _p: dict[str, Any]) -> dict[str, Any]:
        return self._reporter.daily_summary()


if __name__ == "__main__":
    config = AgentConfig.load("forge")
    ForgeAgent("forge", config).run()
