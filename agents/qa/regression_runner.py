"""
Regression runner — executes Playwright e2e test suites per product.

Triggered by deploy agent on success. Filters tests by per-product tag.
Alerts dev and reporting agents on failure.
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


def enqueue_dev_alert(
    product: str,
    repo: str,
    failed: int,
    error_output: str,
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
                "issue_body": f"Regression suite failed for {product}: {failed} test(s) failed",
                "error_logs": error_output[:500],
            },
            priority=1,
        )
    except Exception as exc:
        logger.warning("dev_alert_failed", product=product, error=str(exc))


def enqueue_reporting_alert(
    product: str,
    failed: int,
    passed: int,
    triggered_by: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="reporting",
            payload={
                "action": "regression_failure_alert",
                "product": product,
                "failed": failed,
                "passed": passed,
                "triggered_by": triggered_by,
            },
        )
    except Exception as exc:
        logger.warning("reporting_alert_failed", product=product, error=str(exc))


class RegressionRunner:

    def __init__(self, db: QaDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._repos_path = cfg.get("repos_path", "/repos")
        self._timeout = int(cfg.get("subprocess_timeout_s", 120))

    def run(
        self,
        product: str,
        triggered_by: str = "manual",
    ) -> dict[str, Any]:
        start = time.time()
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        repo = prod_cfg.get("repo", "vance-app")
        tag = prod_cfg.get("playwright_tag", f"@{product}")
        repo_path = os.path.join(self._repos_path, repo)

        result = subprocess.run(
            ["npx", "playwright", "test", "--grep", tag, "--reporter=json"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=self._timeout,
        )

        passed, failed = self._parse_playwright_output(result.stdout)
        success = result.returncode == 0 and failed == 0
        duration_ms = int((time.time() - start) * 1000)

        self._db.save_test_run(
            repo=repo,
            run_type="regression",
            passed=passed,
            failed=failed,
            coverage_pct=0.0,
            duration_ms=duration_ms,
            triggered_by=triggered_by,
        )

        if not success:
            error_output = result.stdout[-500:] + result.stderr[-200:]
            enqueue_dev_alert(
                product=product,
                repo=repo,
                failed=failed,
                error_output=error_output,
            )
            enqueue_reporting_alert(
                product=product,
                failed=failed,
                passed=passed,
                triggered_by=triggered_by,
            )
            logger.error(
                "regression_failed",
                product=product,
                passed=passed,
                failed=failed,
                triggered_by=triggered_by,
            )
        else:
            logger.info(
                "regression_passed",
                product=product,
                passed=passed,
                triggered_by=triggered_by,
            )

        return {
            "product": product,
            "repo": repo,
            "success": success,
            "passed": passed,
            "failed": failed,
            "duration_ms": duration_ms,
            "triggered_by": triggered_by,
        }

    # ------------------------------------------------------------------

    def _parse_playwright_output(self, stdout: str) -> tuple[int, int]:
        try:
            data = json.loads(stdout)
            stats = data.get("stats", {})
            return stats.get("passed", 0), stats.get("failed", 0)
        except (json.JSONDecodeError, AttributeError):
            return 0, 0
