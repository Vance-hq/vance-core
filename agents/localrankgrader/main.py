"""
LocalRankGrader agent — autonomous GBP audit engine.

Actions:
  run_audit          — full GBP audit for a submitted business
  deliver_report     — generate + email PDF report (called from run_audit)
  lead_nurture_grader — send a specific nurture step manually
  benchmark_local    — competitive context for an audit
  grader_analytics   — daily funnel metrics
  auto_publish_result — monthly SEO page generation
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.db.client import get_db
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .analytics import GraderAnalytics
from .auditor import GBPAuditor
from .benchmarker import LocalBenchmarker
from .db import GraderDB
from .email import GraderMailer
from .nurture import NurtureSequencer
from .publisher import SEOPublisher
from .reporter import ReportGenerator

logger = get_logger(__name__)


class LocalRankGraderAgent(BaseAgent):
    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom

        self._db = GraderDB()
        self._mailer = GraderMailer()
        self._auditor = GBPAuditor(
            score_weights=cfg.get("score_weights", {}),
            citation_directories=cfg.get("citation_directories", []),
        )
        self._benchmarker = LocalBenchmarker(
            db=self._db,
            competitor_count=cfg.get("benchmark_competitor_count", 3),
            radius_km=cfg.get("benchmark_radius_km", 10),
        )
        self._reporter = ReportGenerator(db=self._db, mailer=self._mailer)
        self._nurture = NurtureSequencer(
            db=self._db,
            mailer=self._mailer,
            upgrade_nudge_threshold=cfg.get("upgrade_nudge_threshold", 80),
        )
        self._analytics = GraderAnalytics(db=self._db)
        self._publisher = SEOPublisher(db=self._db)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "run_audit": lambda: self._run_audit(p),
            "deliver_report": lambda: self._deliver_report(p),
            "lead_nurture_grader": lambda: self._lead_nurture_grader(p),
            "benchmark_local": lambda: self._benchmark_local(p),
            "grader_analytics": lambda: self._grader_analytics(p),
            "auto_publish_result": lambda: self._auto_publish_result(p),
        }

        handler = dispatch.get(action)
        if not handler:
            raise ValueError(f"Unknown local_rank_grader action: {action}")

        logger.info("grader_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM grader_audits LIMIT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Action: run_audit
    # Payload: business_name, place_id?, address?, contact_email, contact_name?, keyword?
    # ------------------------------------------------------------------

    def _run_audit(self, p: dict[str, Any]) -> dict[str, Any]:
        business_name = p["business_name"]
        contact_email = p["contact_email"]
        contact_name = p.get("contact_name")
        place_id = p.get("place_id")
        address = p.get("address")
        keyword = p.get("keyword")

        logger.info("run_audit_start", business=business_name, email=contact_email)

        audit_result = self._auditor.audit(
            business_name=business_name,
            place_id=place_id,
            address=address,
            keyword=keyword,
        )

        audit_id = self._db.insert_audit(
            business_name=business_name,
            place_id=audit_result.get("place_id"),
            address=audit_result.get("address"),
            contact_email=contact_email,
            contact_name=contact_name,
            overall_score=audit_result["overall_score"],
            category_scores=audit_result["category_scores"],
            recommendations=audit_result["recommendations"],
            raw_places_data=audit_result["raw_places_data"],
        )

        benchmarks = self._benchmarker.benchmark(
            audit_id=audit_id,
            audit_data={**audit_result, "business_name": business_name},
        )

        lead_id = self._db.create_lead(
            audit_id=audit_id,
            email=contact_email,
            contact_name=contact_name,
        )

        report_data: dict[str, Any] = {}
        try:
            report_data = self._reporter.deliver(
                audit_id=audit_id,
                audit_data={**audit_result, "business_name": business_name, "contact_email": contact_email, "contact_name": contact_name},
                benchmarks=benchmarks,
                lead_id=lead_id,
            )
        except Exception as exc:
            logger.error("report_delivery_failed", audit_id=audit_id, error=str(exc))

        self._nurture.schedule_sequence(
            lead_id=lead_id,
            audit_data={**audit_result, "business_name": business_name},
        )

        logger.info(
            "run_audit_complete",
            audit_id=audit_id,
            lead_id=lead_id,
            score=audit_result["overall_score"],
            business=business_name,
        )
        return {
            "audit_id": audit_id,
            "lead_id": lead_id,
            "overall_score": audit_result["overall_score"],
            "category_scores": audit_result["category_scores"],
            "report_url": report_data.get("report_url"),
            "benchmarks_count": len(benchmarks),
        }

    # ------------------------------------------------------------------
    # Action: deliver_report
    # Payload: audit_id, lead_id
    # Regenerates and resends an existing audit's report.
    # ------------------------------------------------------------------

    def _deliver_report(self, p: dict[str, Any]) -> dict[str, Any]:
        audit = self._db.get_audit(p["audit_id"])
        if not audit:
            raise ValueError(f"Audit not found: {p['audit_id']}")
        if not p.get("lead_id"):
            raise ValueError("deliver_report requires lead_id in payload")
        lead_id = p["lead_id"]
        benchmarks = self._db.get_benchmarks(p["audit_id"])
        return self._reporter.deliver(
            audit_id=p["audit_id"],
            audit_data=audit,
            benchmarks=benchmarks,
            lead_id=lead_id,
        )

    # ------------------------------------------------------------------
    # Action: lead_nurture_grader
    # Payload: lead_id, step (1-5)
    # ------------------------------------------------------------------

    def _lead_nurture_grader(self, p: dict[str, Any]) -> dict[str, Any]:
        return self._nurture.send_step(
            lead_id=p["lead_id"],
            step=int(p.get("step", 2)),
        )

    # ------------------------------------------------------------------
    # Action: benchmark_local
    # Payload: audit_id
    # ------------------------------------------------------------------

    def _benchmark_local(self, p: dict[str, Any]) -> dict[str, Any]:
        audit = self._db.get_audit(p["audit_id"])
        if not audit:
            raise ValueError(f"Audit not found: {p['audit_id']}")
        benchmarks = self._benchmarker.benchmark(
            audit_id=p["audit_id"],
            audit_data=audit,
        )
        return {"benchmarks": benchmarks, "count": len(benchmarks)}

    # ------------------------------------------------------------------
    # Action: grader_analytics
    # ------------------------------------------------------------------

    def _grader_analytics(self, _p: dict[str, Any]) -> dict[str, Any]:
        return {
            "daily": self._analytics.daily_summary(),
            "weekly_top": self._analytics.weekly_industry_report(),
        }

    # ------------------------------------------------------------------
    # Action: auto_publish_result
    # ------------------------------------------------------------------

    def _auto_publish_result(self, _p: dict[str, Any]) -> dict[str, Any]:
        return self._publisher.publish_monthly()


if __name__ == "__main__":
    config = AgentConfig.load("local_rank_grader")
    LocalRankGraderAgent("local_rank_grader", config).run()
