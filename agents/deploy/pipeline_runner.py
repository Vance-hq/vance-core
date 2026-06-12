"""
CI pipeline runner — lint → unit tests → integration tests → build →
staging deploy → smoke test.

On success: posts green check to PR, notifies dev agent.
On failure: posts error details to PR, blocks merge, notifies dev agent.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import httpx

from shared.logger import get_logger

from .db import DeployDB

logger = get_logger(__name__)

_STEPS = ["lint", "unit_tests", "integration_tests", "build", "staging_deploy", "smoke_test"]


def _enqueue_dev_notification(
    repo: str,
    pr_number: int,
    success: bool,
    failed_step: str | None,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="dev",
            payload={
                "action": "ci_result",
                "repo": repo,
                "pr_number": pr_number,
                "success": success,
                "failed_step": failed_step,
            },
        )
    except Exception as exc:
        logger.warning("dev_notify_failed", repo=repo, error=str(exc))


class CIPipelineRunner:

    def __init__(self, db: DeployDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos_path = cfg.get("repos_path", "/repos")
        self._timeout = int(cfg.get("subprocess_timeout_s", 300))
        self._github_token = cfg.get("github_token", "")
        self._github_org = cfg.get("github_org", "vance-hq")

    # ------------------------------------------------------------------

    def run(
        self,
        repo: str,
        pr_number: int,
        branch: str,
        build_id: str = "",
    ) -> dict[str, Any]:
        start_ms = int(time.monotonic() * 1000)
        run_id = self._db.save_pipeline_run(
            repo=repo,
            pr_number=pr_number,
            branch=branch,
            build_id=build_id,
        )

        repo_path = os.path.join(self._repos_path, repo)
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})

        steps: list[dict[str, Any]] = []
        failed_step: str | None = None

        for step_name in _STEPS:
            step_result = self._run_step(step_name, repo, repo_path, repo_cfg, branch)
            steps.append(step_result)

            if not step_result["success"]:
                failed_step = step_name
                break

        success = failed_step is None
        duration_ms = int(time.monotonic() * 1000) - start_ms

        self._db.update_pipeline_run(
            run_id=run_id,
            status="success" if success else "failed",
            steps=steps,
            duration_ms=duration_ms,
        )

        self._post_pr_status(repo, pr_number, success, failed_step, steps)
        _enqueue_dev_notification(repo, pr_number, success, failed_step)

        logger.info(
            "ci_pipeline_complete",
            repo=repo,
            pr_number=pr_number,
            success=success,
            failed_step=failed_step,
        )

        return {
            "run_id": run_id,
            "repo": repo,
            "pr_number": pr_number,
            "success": success,
            "failed_step": failed_step,
            "steps": steps,
            "duration_ms": duration_ms,
        }

    def _run_step(
        self,
        step_name: str,
        repo: str,
        repo_path: str,
        repo_cfg: dict[str, Any],
        branch: str,
    ) -> dict[str, Any]:
        step_start = time.monotonic()
        repo_type = repo_cfg.get("type", "python")

        try:
            if step_name == "staging_deploy":
                result = self._staging_deploy(repo, repo_cfg, branch)
                return {
                    "name": step_name,
                    "success": result.get("success", False),
                    "output": result.get("url", ""),
                    "duration_ms": int((time.monotonic() - step_start) * 1000),
                }

            if step_name == "smoke_test":
                result = self._smoke_test(repo_cfg)
                return {
                    "name": step_name,
                    "success": result["ok"],
                    "output": result.get("status", ""),
                    "duration_ms": int((time.monotonic() - step_start) * 1000),
                }

            cmd = self._step_cmd(step_name, repo_type)
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=self._timeout,
            )
            output = (proc.stdout + proc.stderr)[:1000]
            return {
                "name": step_name,
                "success": proc.returncode == 0,
                "output": output,
                "duration_ms": int((time.monotonic() - step_start) * 1000),
            }
        except subprocess.TimeoutExpired:
            return {
                "name": step_name,
                "success": False,
                "output": f"step timed out after {self._timeout}s",
                "duration_ms": int((time.monotonic() - step_start) * 1000),
            }
        except Exception as exc:
            return {
                "name": step_name,
                "success": False,
                "output": str(exc),
                "duration_ms": int((time.monotonic() - step_start) * 1000),
            }

    def _step_cmd(self, step_name: str, repo_type: str) -> list[str]:
        if repo_type == "node":
            return {
                "lint":              ["npm", "run", "lint"],
                "unit_tests":        ["npm", "test", "--", "--ci"],
                "integration_tests": ["npm", "run", "test:integration", "--", "--ci"],
                "build":             ["npm", "run", "build"],
            }.get(step_name, ["echo", step_name])
        return {
            "lint":              ["ruff", "check", "."],
            "unit_tests":        ["pytest", "-x", "-q"],
            "integration_tests": ["pytest", "tests/integration/", "-q"],
            "build":             ["python", "-m", "build"],
        }.get(step_name, ["echo", step_name])

    def _staging_deploy(self, repo: str, repo_cfg: dict[str, Any], branch: str) -> dict[str, Any]:
        from agents.integrations.connectors.vercel import VercelConnector

        project_id = repo_cfg.get("vercel_project_id", repo)
        vc = VercelConnector(called_by="deploy.pipeline", method_name="trigger_staging")
        resp = vc.trigger_deploy(project_id=project_id, git_ref=branch)
        deployment_id = resp.get("uid", resp.get("id", ""))
        url = resp.get("url", "")
        return {"success": bool(deployment_id), "deployment_id": deployment_id, "url": url}

    def _smoke_test(self, repo_cfg: dict[str, Any]) -> dict[str, Any]:
        staging_url = repo_cfg.get("staging_url", "")
        if not staging_url:
            return {"ok": True, "status": "no staging url configured"}
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(f"{staging_url}/health")
                return {"ok": resp.is_success, "status": resp.status_code}
        except Exception as exc:
            return {"ok": False, "status": str(exc)}

    def _post_pr_status(
        self,
        repo: str,
        pr_number: int,
        success: bool,
        failed_step: str | None,
        steps: list[dict[str, Any]],
    ) -> None:
        if not self._github_token or not pr_number:
            return
        try:
            from agents.integrations.connectors.github import GitHubConnector

            gh = GitHubConnector(called_by="deploy.pipeline", method_name="post_pr_comment")
            if success:
                body = "✅ **CI passed** — all pipeline steps green. Ready to merge."
            else:
                failed = next((s for s in steps if s["name"] == failed_step), {})
                body = (
                    f"❌ **CI failed** at `{failed_step}`\n\n"
                    f"```\n{failed.get('output', '')[:500]}\n```\n\n"
                    "Merge is blocked until CI passes."
                )
            gh.post_pr_comment(repo=repo, pr_number=pr_number, body=body)

            if not success:
                gh.add_label(repo=repo, issue_number=pr_number, label="ci-failing")
        except Exception as exc:
            logger.warning("pr_status_post_failed", repo=repo, pr=pr_number, error=str(exc))
