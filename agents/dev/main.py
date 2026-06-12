"""
Dev agent — autonomous software builds, bug fixes, deployments, and dependency updates.

Actions:
  build_feature      — build a feature via Claude Code subprocess + PR
  fix_bug            — fix a GitHub issue via Claude Code + close issue on PR
  run_tests          — execute test suite, enqueue fix_bug on failure
  deploy             — trigger Vercel deploy, poll, rollback on failure
  dependency_update  — update minor/patch deps automatically; flag major updates
  hotfix             — emergency fix: commit to main, deploy, create post-mortem
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .builder import Builder
from .db import DevDB
from .dep_updater import DependencyUpdater
from .deployer import Deployer
from .test_runner import TestRunner

logger = get_logger(__name__)


class DevAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = DevDB()
        self._builder = Builder(self._db, cfg)
        self._test_runner = TestRunner(self._db, cfg)
        self._deployer = Deployer(self._db, cfg)
        self._dep_updater = DependencyUpdater(self._db, cfg)

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "build_feature":     lambda: self._handle_build_feature(p),
            "fix_bug":           lambda: self._handle_fix_bug(p),
            "run_tests":         lambda: self._handle_run_tests(p),
            "deploy":            lambda: self._handle_deploy(p),
            "dependency_update": lambda: self._handle_dep_update(p),
            "hotfix":            lambda: self._handle_hotfix(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown dev action: {action}"},
            )

        logger.info("dev_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_recent_deployments(repo="vance-app", limit=1)
            return True
        except Exception:
            return False

    def _handle_build_feature(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        feature_description = p.get("feature_description", "")
        acceptance_criteria = p.get("acceptance_criteria", "")
        target_branch = p.get("target_branch", "")
        if not all([repo, feature_description, acceptance_criteria, target_branch]):
            return {"error": "repo, feature_description, acceptance_criteria, target_branch required"}
        return self._builder.build_feature(
            repo=repo,
            feature_description=feature_description,
            acceptance_criteria=acceptance_criteria,
            target_branch=target_branch,
        )

    def _handle_fix_bug(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        issue_number = p.get("issue_number", 0)
        if not repo or not issue_number:
            return {"error": "repo and issue_number required"}
        return self._builder.fix_bug(
            repo=repo,
            issue_number=int(issue_number),
            issue_body=p.get("issue_body", ""),
            error_logs=p.get("error_logs", ""),
        )

    def _handle_run_tests(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        if not repo:
            return {"error": "repo required"}
        return self._test_runner.run(
            repo=repo,
            test_type=p.get("test_type", "unit"),
        )

    def _handle_deploy(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        if not repo:
            return {"error": "repo required"}
        return self._deployer.deploy(
            repo=repo,
            environment=p.get("environment", "production"),
            task_id=p.get("task_id", ""),
        )

    def _handle_dep_update(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        if not repo:
            return {"error": "repo required"}
        return self._dep_updater.update(repo=repo)

    def _handle_hotfix(self, p: dict[str, Any]) -> dict[str, Any]:
        repo = p.get("repo", "")
        description = p.get("description", "")
        if not repo or not description:
            return {"error": "repo and description required"}
        return self._builder.hotfix(
            repo=repo,
            description=description,
            error_context=p.get("error_context", ""),
        )


if __name__ == "__main__":
    config = AgentConfig.load("dev")
    DevAgent("dev", config).run()
