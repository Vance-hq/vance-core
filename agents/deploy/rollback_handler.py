"""
Rollback handler — reverts production to the previous known-good deployment.

Triggers:
  - QA regression failure (automated)
  - Manual voice command "rollback [product]"

Actions:
  1. Fetch previous successful deployment from DB
  2. Execute rollback via Vercel
  3. Mark current deployment as rolled_back in DB
  4. Notify all agents
  5. If > 100 users affected: enqueue support agent proactive message
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared.logger import get_logger

from .db import DeployDB

logger = get_logger(__name__)

SUPPORT_NOTIFY_USER_THRESHOLD = 100


def _notify_all_agents(
    repo: str,
    rollback_version: str,
    reason: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        for agent in ("dev", "qa", "reporting"):
            queue.push(
                agent=agent,
                payload={
                    "action": "rollback_notification",
                    "repo": repo,
                    "rollback_version": rollback_version,
                    "reason": reason,
                },
            )
    except Exception as exc:
        logger.warning("rollback_notify_failed", repo=repo, error=str(exc))


def _enqueue_support_message(repo: str, rollback_version: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="support",
            payload={
                "action": "proactive_message",
                "topic": "service_disruption",
                "repo": repo,
                "rollback_version": rollback_version,
                "message": (
                    f"We just deployed a fix to address a brief service disruption "
                    f"affecting {repo}. Everything is back to normal."
                ),
            },
        )
    except Exception as exc:
        logger.warning("support_notify_failed", repo=repo, error=str(exc))


class RollbackHandler:

    def __init__(self, db: DeployDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    # ------------------------------------------------------------------

    def rollback(
        self,
        repo: str,
        environment: str = "production",
        reason: str = "manual",
        current_version: str | None = None,
        affected_users: int = 0,
    ) -> dict[str, Any]:
        current = (
            self._db.get_last_successful_deployment(repo, environment)
            if not current_version
            else {"version": current_version}
        )
        current_ver = current.get("version", "") if current else ""

        previous = self._db.get_previous_deployment(
            repo=repo,
            environment=environment,
            before_version=current_ver,
        )

        if not previous:
            logger.error("rollback_no_previous", repo=repo, environment=environment)
            return {
                "success": False,
                "reason": "no previous successful deployment to roll back to",
            }

        rollback_version = previous["version"]
        success = self._execute_rollback(repo, environment, rollback_version)

        if success:
            if current_ver:
                self._db.update_deployment(
                    deployment_id=current.get("id", ""),
                    status="rolled_back",
                    deployed_at=datetime.now(timezone.utc),
                )

            _notify_all_agents(repo, rollback_version, reason)

            if affected_users >= SUPPORT_NOTIFY_USER_THRESHOLD:
                _enqueue_support_message(repo, rollback_version)

            logger.info(
                "rollback_success",
                repo=repo,
                rollback_version=rollback_version,
                reason=reason,
            )

        return {
            "success": success,
            "repo": repo,
            "environment": environment,
            "rolled_back_to": rollback_version,
            "reason": reason,
            "support_notified": affected_users >= SUPPORT_NOTIFY_USER_THRESHOLD,
        }

    # ------------------------------------------------------------------

    def _execute_rollback(
        self,
        repo: str,
        environment: str,
        version: str,
    ) -> bool:
        try:
            from agents.integrations.connectors.vercel import VercelConnector

            repo_cfg = self._cfg.get("repos", {}).get(repo, {})
            project_id = repo_cfg.get("vercel_project_id", repo)

            vc = VercelConnector(called_by="deploy.rollback", method_name="rollback")
            vc.rollback(project_id=project_id, deployment_id=version)
            logger.info("vercel_rollback_executed", repo=repo, version=version)
            return True
        except Exception as exc:
            logger.error("rollback_execution_failed", repo=repo, version=version, error=str(exc))
            return False
