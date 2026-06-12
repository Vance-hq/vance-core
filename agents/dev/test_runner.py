"""
Test runner — executes test suites and parses results.

Detects repo type (python vs node) from config, runs appropriate command,
parses pass/fail counts from output, and enqueues fix_bug on failure.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any

from shared.logger import get_logger

from .db import DevDB

logger = get_logger(__name__)

_PYTEST_PASS_RE = re.compile(r"(\d+) passed")
_PYTEST_FAIL_RE = re.compile(r"(\d+) failed")
_NPM_PASS_RE = re.compile(r"(\d+) passing|Tests:\s+(\d+) passed")
_NPM_FAIL_RE = re.compile(r"(\d+) failing|Tests:\s+(\d+) failed")


def enqueue_fix_bug(
    repo: str,
    error_context: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="dev",
            payload={
                "action": "fix_bug",
                "repo": repo,
                "issue_number": 0,
                "issue_body": f"Tests failing:\n{error_context}",
                "error_logs": error_context,
            },
        )
    except Exception as exc:
        logger.warning("fix_bug_enqueue_failed", repo=repo, error=str(exc))


class TestRunner:

    def __init__(self, db: DevDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos_path = cfg.get("repos_path", "/repos")
        self._timeout = int(cfg.get("subprocess_timeout_s", 300))

    def run(
        self,
        repo: str,
        test_type: str = "unit",
    ) -> dict[str, Any]:
        start = time.time()
        repo_path = os.path.join(self._repos_path, repo)
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        repo_type = repo_cfg.get("type", "python")

        cmd = self._build_cmd(repo_type, test_type)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=self._timeout,
        )

        output = result.stdout + result.stderr
        passed, failed = self._parse_counts(output, repo_type)
        success = result.returncode == 0

        duration = time.time() - start
        self._db.save_build_log(
            repo=repo,
            task_type=f"run_tests_{test_type}",
            success=success,
            duration_seconds=duration,
            error_msg=output[:500] if not success else None,
        )

        if not success:
            enqueue_fix_bug(repo=repo, error_context=output[:1000])

        logger.info(
            "tests_complete",
            repo=repo,
            test_type=test_type,
            passed=passed,
            failed=failed,
            success=success,
        )

        return {
            "repo": repo,
            "test_type": test_type,
            "success": success,
            "passed": passed,
            "failed": failed,
            "output": output[:500],
        }

    # ------------------------------------------------------------------

    def _build_cmd(self, repo_type: str, test_type: str) -> list[str]:
        if repo_type == "node":
            if test_type == "e2e":
                return ["npm", "run", "test:e2e", "--", "--ci"]
            if test_type == "integration":
                return ["npm", "run", "test:integration", "--", "--ci"]
            return ["npm", "test", "--", "--ci"]
        else:
            if test_type == "e2e":
                return ["pytest", "tests/e2e/", "-v"]
            if test_type == "integration":
                return ["pytest", "tests/integration/", "-v"]
            return ["pytest", "-x", "-q"]

    def _parse_counts(self, output: str, repo_type: str) -> tuple[int, int]:
        if repo_type == "node":
            pass_m = _NPM_PASS_RE.search(output)
            fail_m = _NPM_FAIL_RE.search(output)
        else:
            pass_m = _PYTEST_PASS_RE.search(output)
            fail_m = _PYTEST_FAIL_RE.search(output)

        passed = int(next((g for g in (pass_m.groups() if pass_m else []) if g), 0))
        failed = int(next((g for g in (fail_m.groups() if fail_m else []) if g), 0))
        return passed, failed
