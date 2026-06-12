"""
Deploy agent — CI/CD orchestration, production promotions, rollbacks,
environment sync, and release notes.

Actions:
  ci_pipeline            — Run full CI pipeline on a PR (lint→tests→build→staging→smoke)
  promote_to_production  — Promote staging build to production with pre-checks
  rollback               — Revert production to previous known-good version
  environment_sync       — Sync DB schema from production to staging (weekly)
  release_notes          — Auto-generate release notes from merged PRs
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .db import DeployDB
from .env_syncer import EnvSyncer
from .pipeline_runner import CIPipelineRunner
from .promoter import Promoter
from .release_notes import ReleaseNotesGenerator
from .rollback_handler import RollbackHandler

logger = get_logger(__name__)


class DeployAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = DeployDB()
        self._pipeline = CIPipelineRunner(self._db, cfg)
        self._promoter = Promoter(self._db, cfg)
        self._rollback = RollbackHandler(self._db, cfg)
        self._env_syncer = EnvSyncer(cfg)
        self._release_notes = ReleaseNotesGenerator(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "ci_pipeline":           lambda: self._handle_ci_pipeline(p),
            "promote_to_production": lambda: self._handle_promote(p),
            "rollback":              lambda: self._handle_rollback(p),
            "environment_sync":      lambda: self._handle_env_sync(p),
            "release_notes":         lambda: self._handle_release_notes(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown deploy action: {action}"},
            )

        logger.info("deploy_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_latest_pipeline_run(repo="vance-app")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # ci_pipeline
    # ------------------------------------------------------------------

    def _handle_ci_pipeline(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        pr_number = int(p.get("pr_number", 0))
        branch = p.get("branch", "main")
        build_id = p.get("build_id", "")

        if not repo:
            return {"error": "repo required"}

        return self._pipeline.run(
            repo=repo,
            pr_number=pr_number,
            branch=branch,
            build_id=build_id,
        )

    # ------------------------------------------------------------------
    # promote_to_production
    # ------------------------------------------------------------------

    def _handle_promote(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        build_id = p.get("build_id", "")

        if not repo or not build_id:
            return {"error": "repo and build_id required"}

        result = self._promoter.promote(
            repo=repo,
            build_id=build_id,
            task_id=p.get("task_id", ""),
        )

        if result.get("success") and not result.get("blocked"):
            self._trigger_auto_rollback_on_regression(repo, result)

        return result

    def _trigger_auto_rollback_on_regression(
        self,
        repo: str,
        promote_result: dict[str, Any],
    ) -> None:
        """Check if QA regression was enqueued — rollback is triggered by QA agent on failure."""
        pass

    # ------------------------------------------------------------------
    # rollback
    # ------------------------------------------------------------------

    def _handle_rollback(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        if not repo:
            return {"error": "repo required"}

        return self._rollback.rollback(
            repo=repo,
            environment=p.get("environment", "production"),
            reason=p.get("reason", "manual"),
            current_version=p.get("current_version"),
            affected_users=int(p.get("affected_users", 0)),
        )

    # ------------------------------------------------------------------
    # environment_sync
    # ------------------------------------------------------------------

    def _handle_env_sync(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        if not repo:
            return {"error": "repo required"}

        return self._env_syncer.sync(repo=repo)

    # ------------------------------------------------------------------
    # release_notes
    # ------------------------------------------------------------------

    def _handle_release_notes(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        tag = p.get("tag", "")

        if not repo or not tag:
            return {"error": "repo and tag required"}

        return self._release_notes.generate(
            repo=repo,
            tag=tag,
            build_id=p.get("build_id", ""),
        )


if __name__ == "__main__":
    config = AgentConfig.load("deploy")
    DeployAgent("deploy", config).run()
