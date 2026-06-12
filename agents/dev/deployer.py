"""
Deployer — triggers Vercel deployments, polls for status, handles rollback.

On success: updates DB, notifies reporting agent.
On failure: triggers Vercel rollback, updates DB with error status.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from agents.integrations.connectors.vercel import VercelConnector
from shared.logger import get_logger

from .db import DevDB

logger = get_logger(__name__)

_TERMINAL_STATES = {"READY", "ERROR", "CANCELED"}
_MAX_POLL_ATTEMPTS = 60


def notify_reporting(
    repo: str,
    environment: str,
    deployment_id: str,
    url: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="reporting",
            payload={
                "action": "deployment_success",
                "repo": repo,
                "environment": environment,
                "deployment_id": deployment_id,
                "url": url,
            },
        )
    except Exception as exc:
        logger.warning("notify_reporting_failed", repo=repo, error=str(exc))


class Deployer:

    def __init__(self, db: DevDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._poll_interval = float(cfg.get("deploy_poll_interval_s", 5))

    def deploy(
        self,
        repo: str,
        environment: str = "production",
        task_id: str = "",
    ) -> dict[str, Any]:
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        project_id = repo_cfg.get("vercel_project_id", repo)
        default_branch = repo_cfg.get("default_branch", "main")

        vc = VercelConnector(called_by="dev.deployer", method_name="deploy")

        # Trigger
        trigger_resp = vc.trigger_deploy(project_id=project_id, git_ref=default_branch)
        deployment_id = trigger_resp.get("uid", trigger_resp.get("id", ""))
        deploy_url = trigger_resp.get("url", "")

        # Save pending record
        db_id = self._db.save_deployment(
            repo=repo,
            environment=environment,
            version=deployment_id,
            status="pending",
            deployed_by_task_id=task_id or deployment_id,
        )

        # Poll
        for _ in range(_MAX_POLL_ATTEMPTS):
            status_resp = vc.get_deployment_status(deployment_id)
            state = status_resp.get("readyState", "BUILDING")
            deploy_url = status_resp.get("url", deploy_url)

            if state in _TERMINAL_STATES:
                break

            if self._poll_interval > 0:
                time.sleep(self._poll_interval)

        success = state == "READY"

        self._db.update_deployment(
            deployment_id=db_id,
            status="success" if success else "failed",
            deployed_at=datetime.now(timezone.utc),
        )

        if success:
            notify_reporting(
                repo=repo,
                environment=environment,
                deployment_id=deployment_id,
                url=deploy_url,
            )
            logger.info("deployment_success", repo=repo, env=environment, deployment_id=deployment_id)
        else:
            # Rollback to last good deployment
            last_good = self._db.get_last_deployment(repo=repo, environment=environment)
            if last_good:
                vc.rollback(project_id=project_id, deployment_id=last_good.get("version", ""))
            logger.error("deployment_failed", repo=repo, env=environment, state=state)

        return {
            "success": success,
            "repo": repo,
            "environment": environment,
            "deployment_id": deployment_id,
            "url": deploy_url,
            "state": state,
        }
