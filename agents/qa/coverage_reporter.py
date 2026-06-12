"""
Coverage reporter — runs pytest-cov or jest --coverage, finds files below
threshold, enqueues write_tests for the 3 worst, and notifies reporting.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

from shared.logger import get_logger

from .db import QaDB

logger = get_logger(__name__)

_WORST_FILES_LIMIT = 3


def enqueue_write_tests(repo: str, file_path: str) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="dev",
            payload={
                "action": "write_tests",
                "repo": repo,
                "feature_code": f"# File: {file_path}",
                "acceptance_criteria": f"Increase test coverage for {file_path}",
                "branch": "main",
            },
            priority=4,
        )
    except Exception as exc:
        logger.warning("write_tests_enqueue_failed", repo=repo, file=file_path, error=str(exc))


def notify_reporting(repo: str, coverage_pct: float, low_coverage_files: list[str]) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="reporting",
            payload={
                "action": "coverage_report",
                "repo": repo,
                "coverage_pct": coverage_pct,
                "low_coverage_files": low_coverage_files,
            },
        )
    except Exception as exc:
        logger.warning("notify_reporting_failed", repo=repo, error=str(exc))


class CoverageReporter:

    def __init__(self, db: QaDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos_path = cfg.get("repos_path", "/repos")
        self._timeout = int(cfg.get("subprocess_timeout_s", 120))
        self._threshold = float(cfg.get("coverage_threshold_pct", 60.0))

    def report(self, repo: str) -> dict[str, Any]:
        start = time.time()
        repo_cfg = self._cfg.get("repos", {}).get(repo, {})
        repo_type = repo_cfg.get("type", "python")
        repo_path = os.path.join(self._repos_path, repo)

        result = subprocess.run(
            self._coverage_cmd(repo_type),
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=self._timeout,
        )

        total_pct, file_coverages = self._parse_coverage(result.stdout, repo_type)
        duration_ms = int((time.time() - start) * 1000)

        low_coverage_files = sorted(
            [fp for fp, pct in file_coverages.items() if pct < self._threshold],
            key=lambda fp: file_coverages[fp],
        )

        self._db.save_test_run(
            repo=repo,
            run_type="coverage",
            passed=0,
            failed=0,
            coverage_pct=total_pct,
            duration_ms=duration_ms,
            triggered_by="scheduled",
        )

        worst = low_coverage_files[:_WORST_FILES_LIMIT]
        for fp in worst:
            enqueue_write_tests(repo=repo, file_path=fp)

        notify_reporting(
            repo=repo,
            coverage_pct=total_pct,
            low_coverage_files=low_coverage_files,
        )

        logger.info(
            "coverage_report_done",
            repo=repo,
            total_pct=total_pct,
            low_files=len(low_coverage_files),
        )

        return {
            "repo": repo,
            "coverage_pct": total_pct,
            "low_coverage_files": low_coverage_files,
            "files_enqueued_for_tests": worst,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _coverage_cmd(repo_type: str) -> list[str]:
        if repo_type == "python":
            return ["pytest", "--cov=.", "--cov-report=json:-", "-q", "--tb=no"]
        return ["npm", "test", "--", "--coverage", "--coverageReporters=json", "--watchAll=false"]

    @staticmethod
    def _parse_coverage(stdout: str, repo_type: str) -> tuple[float, dict[str, float]]:
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            return 0.0, {}

        if repo_type == "python":
            total_pct = data.get("totals", {}).get("percent_covered", 0.0)
            file_coverages = {
                fp: info["summary"]["percent_covered"]
                for fp, info in data.get("files", {}).items()
                if isinstance(info, dict) and "summary" in info
            }
        else:
            total_pct = data.get("total", {}).get("lines", {}).get("pct", 0.0)
            file_coverages = {
                fp: info["lines"]["pct"]
                for fp, info in data.items()
                if fp != "total" and isinstance(info, dict) and "lines" in info
            }

        return total_pct, file_coverages
