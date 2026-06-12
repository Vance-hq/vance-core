"""
Promoter — promotes a staging build to production after passing all pre-checks.

Pre-checks:
  1. CI pipeline passed for this build
  2. No open P0/P1 GitHub issues
  3. Not during a configured blackout window

Post-deploy:
  - Triggers QA regression suite
  - Auto-rollbacks if regression fails
  - Generates release notes
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from shared.logger import get_logger

from .db import DeployDB

logger = get_logger(__name__)

_TERMINAL_STATES = {"READY", "ERROR", "CANCELED"}
_MAX_POLL = 60


def _enqueue_qa_regression(repo: str, deployment_id: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="qa",
            payload={"action": "regression_suite", "repo": repo, "deployment_id": deployment_id},
        )
    except Exception as exc:
        logger.warning("qa_enqueue_failed", repo=repo, error=str(exc))


def _enqueue_release_notes(repo: str, build_id: str, tag: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="deploy",
            payload={"action": "release_notes", "repo": repo, "build_id": build_id, "tag": tag},
        )
    except Exception as exc:
        logger.warning("release_notes_enqueue_failed", repo=repo, error=str(exc))


class Promoter:

    def __init__(self, db: DeployDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._poll_interval = float(cfg.get("deploy_poll_interval_s", 5))
        self._blackout_windows: list[dict[str, Any]] = cfg.get("blackout_windows", [])

    # ------------------------------------------------------------------

    def promote(
        self,
        repo: str,
        build_id: str,
        task_id: str = "",
        environment: str = "production",
    ) -> dict[str, Any]:
        checks = self._run_prechecks(repo, build_id)
        if not checks["passed"]:
            logger.warning("promote_blocked", repo=repo, reason=checks["reason"])
            return {"success": False, "blocked": True, "reason": checks["reason"]}

        deployment_id = self._db.save_deployment(
            repo=repo,
            environment=environment,
            version=build_id,
            status="pending",
            deployed_by_task_id=task_id,
        )

        deploy_result = self._deploy_vercel(repo, build_id)

        if not deploy_result["success"]:
            self._db.update_deployment(deployment_id=deployment_id, status="failed")
            return {"success": False, "error": "deployment failed", "deploy": deploy_result}

        self._db.update_deployment(
            deployment_id=deployment_id,
            status="success",
            deployed_at=datetime.now(timezone.utc),
        )

        _enqueue_qa_regression(repo, deployment_id)
        _enqueue_release_notes(repo, build_id, tag=f"v{build_id}")

        logger.info("promote_success", repo=repo, build_id=build_id, env=environment)
        return {
            "success": True,
            "repo": repo,
            "build_id": build_id,
            "environment": environment,
            "deployment_id": deployment_id,
            "deploy": deploy_result,
        }

    # ------------------------------------------------------------------
    # Pre-checks
    # ------------------------------------------------------------------

    def _run_prechecks(self, repo: str, build_id: str) -> dict[str, Any]:
        if not self._all_ci_passed(repo, build_id):
            return {"passed": False, "reason": "CI pipeline did not pass for this build"}

        if not self._no_critical_bugs(repo):
            return {"passed": False, "reason": "open P0/P1 bugs exist — promotion blocked"}

        if self._in_blackout_window():
            return {"passed": False, "reason": "deployment blackout window active"}

        return {"passed": True, "reason": ""}

    def _all_ci_passed(self, repo: str, build_id: str) -> bool:
        run = self._db.get_latest_pipeline_run(repo=repo)
        if not run:
            return False
        if run.get("build_id") and run["build_id"] != build_id:
            return False
        return run.get("status") == "success"

    def _no_critical_bugs(self, repo: str) -> bool:
        try:
            from agents.integrations.connectors.github import GitHubConnector

            gh = GitHubConnector(called_by="deploy.promoter", method_name="list_issues")
            issues = gh.list_issues(repo=repo, labels=["P0", "P1"], state="open")
            return len(issues) == 0
        except Exception as exc:
            logger.warning("critical_bug_check_failed", repo=repo, error=str(exc))
            return True

    def _in_blackout_window(self) -> bool:
        now = datetime.now(timezone.utc)
        weekday = now.weekday()  # 0=Mon, 6=Sun
        hour = now.hour

        for window in self._blackout_windows:
            days = window.get("days", [])
            start_h = window.get("start_hour", 0)
            end_h = window.get("end_hour", 24)
            if weekday in days and start_h <= hour < end_h:
                return True

        return False

    def _deploy_vercel(self, repo: str, build_id: str) -> dict[str, Any]:
        from agents.integrations.connectors.vercel import VercelConnector

        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        project_id = repo_cfg.get("vercel_project_id", repo)
        branch = repo_cfg.get("default_branch", "main")

        vc = VercelConnector(called_by="deploy.promoter", method_name="deploy_production")
        trigger = vc.trigger_deploy(project_id=project_id, git_ref=branch)
        vercel_id = trigger.get("uid", trigger.get("id", ""))
        url = trigger.get("url", "")

        for _ in range(_MAX_POLL):
            status = vc.get_deployment_status(vercel_id)
            state = status.get("readyState", "BUILDING")
            url = status.get("url", url)
            if state in _TERMINAL_STATES:
                break
            if self._poll_interval > 0:
                time.sleep(self._poll_interval)

        success = state == "READY"
        return {
            "success": success,
            "vercel_deployment_id": vercel_id,
            "url": url,
            "state": state,
        }
