"""
QA agent — regression testing, test generation, bug triage,
load testing, and coverage reporting.

Actions:
  run_regression_suite — Playwright e2e per product, alert on failure
  write_tests          — LLM generates unit + integration + e2e tests
  bug_triage           — LLM classifies P0-P3, routes to dev or GitHub
  load_test            — Locust subprocess, alert if p99 > 2000ms
  coverage_report      — pytest-cov / jest coverage; enqueue tests for worst files
"""

from __future__ import annotations

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .bug_triager import BugTriager
from .coverage_reporter import CoverageReporter
from .db import QaDB
from .load_tester import LoadTester
from .regression_runner import RegressionRunner
from .test_writer import TestWriter

logger = get_logger(__name__)


class QaAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = QaDB()
        self._regression = RegressionRunner(self._db, cfg)
        self._writer = TestWriter(self._db, cfg)
        self._triager = BugTriager(self._db, cfg)
        self._load_tester = LoadTester(self._db, cfg)
        self._coverage = CoverageReporter(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "run_regression_suite": lambda: self._handle_regression(p),
            "write_tests":          lambda: self._handle_write_tests(p),
            "bug_triage":           lambda: self._handle_bug_triage(p),
            "load_test":            lambda: self._handle_load_test(p),
            "coverage_report":      lambda: self._handle_coverage(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown qa action: {action}"},
            )

        try:
            output = handler()
            return TaskResult(task_id=task.id, success=True, output=output)
        except Exception as exc:
            logger.error("qa_action_failed", action=action, task_id=task.id, error=str(exc))
            return TaskResult(task_id=task.id, success=False, output={"error": str(exc)})

    def health_check(self) -> bool:
        try:
            self._db.get_recent_runs(repo="vance-app", limit=1)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------

    def _handle_regression(self, p: dict) -> dict:
        return self._regression.run(
            product=p["product"],
            triggered_by=p.get("triggered_by", "manual"),
        )

    def _handle_write_tests(self, p: dict) -> dict:
        return self._writer.write(
            repo=p["repo"],
            feature_code=p.get("feature_code", ""),
            acceptance_criteria=p.get("acceptance_criteria", ""),
            branch=p.get("branch", "main"),
        )

    def _handle_bug_triage(self, p: dict) -> dict:
        return self._triager.triage(
            product=p["product"],
            error_log=p.get("error_log", ""),
            stack_trace=p.get("stack_trace", ""),
            affected_users_count=int(p.get("affected_users_count", 0)),
        )

    def _handle_load_test(self, p: dict) -> dict:
        return self._load_tester.run(
            endpoint=p["endpoint"],
            expected_rps=int(p.get("expected_rps", 10)),
            test_duration_seconds=int(p.get("test_duration_seconds", 60)),
        )

    def _handle_coverage(self, p: dict) -> dict:
        return self._coverage.report(repo=p["repo"])


if __name__ == "__main__":
    config = AgentConfig.load("qa")
    QaAgent("qa", config).run()
