"""Dev agent — Claude Code subprocess runner, Git operations, Vercel deployments."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from agents._base import BaseAgent, AgentConfig
from agents.integrations.connectors.vercel import VercelConnector
from shared.logger import get_logger
from shared.types import Task, TaskResult

logger = get_logger(__name__)

REPOS_PATH = os.environ.get("REPOS_PATH", "/repos")


class DevAgent(BaseAgent):

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")

        if action == "run_claude_code":
            return self._run_claude_code(task)
        if action == "git_push":
            return self._git_push(task)
        if action == "deploy":
            return self._deploy(task)

        return TaskResult(task_id=task.id, success=False, output={"error": f"unknown action: {action}"})

    def health_check(self) -> bool:
        return True

    # ------------------------------------------------------------------

    def _run_claude_code(self, task: Task) -> TaskResult:
        prompt = task.payload.get("prompt", "")
        repo = task.payload.get("repo", "")
        working_dir = os.path.join(REPOS_PATH, repo) if repo else REPOS_PATH

        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=300,
        )
        return TaskResult(
            task_id=task.id,
            success=result.returncode == 0,
            output={"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode},
        )

    def _git_push(self, task: Task) -> TaskResult:
        repo = task.payload.get("repo", "")
        message = task.payload.get("message", "chore: automated commit")
        working_dir = os.path.join(REPOS_PATH, repo) if repo else REPOS_PATH

        cmds = [
            ["git", "add", "-A"],
            ["git", "commit", "-m", message],
            ["git", "push"],
        ]
        for cmd in cmds:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=working_dir)
            if result.returncode != 0:
                return TaskResult(
                    task_id=task.id,
                    success=False,
                    output={"error": result.stderr, "cmd": " ".join(cmd)},
                )
        return TaskResult(task_id=task.id, success=True, output={"message": message})

    def _deploy(self, task: Task) -> TaskResult:
        project = task.payload.get("project", "")
        environment = task.payload.get("environment", "production")
        vercel = VercelConnector(called_by="dev", method_name="deploy")
        result = vercel.deploy(project_id=project, target=environment)
        return TaskResult(task_id=task.id, success=True, output=result)


if __name__ == "__main__":
    config = AgentConfig.load("dev")
    DevAgent("dev", config).run()
