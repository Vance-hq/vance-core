"""
Load tester — runs Locust against an endpoint and parses percentile latencies.

If p99 > threshold (default 2000ms) enqueues a performance optimization task
to the dev agent.
"""

from __future__ import annotations

import csv
import io
import subprocess
import time
from typing import Any

from shared.logger import get_logger

from .db import QaDB

logger = get_logger(__name__)

# CSV column indices (0-based) from Locust stats output:
# Name, Request Count, Failure Count, Median, Average, Min, Max,
# Avg Content Size, Requests/s, Failures/s,
# 50%, 66%, 75%, 80%, 90%, 95%, 98%, 99%, 99.9%, 99.99%, 100%
_COL_REQUESTS = 1
_COL_FAILURES = 2
_COL_RPS = 8
_COL_P50 = 10
_COL_P95 = 15
_COL_P99 = 17


def enqueue_optimization(endpoint: str, p99_ms: float) -> None:
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="dev",
            payload={
                "action": "build_feature",
                "repo": "vance-app",
                "description": (
                    f"Performance optimization: {endpoint} p99={p99_ms:.0f}ms "
                    f"exceeds 2000ms threshold. Investigate and optimize."
                ),
            },
            priority=3,
        )
    except Exception as exc:
        logger.warning("optimization_enqueue_failed", endpoint=endpoint, error=str(exc))


class LoadTester:

    def __init__(self, db: QaDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._timeout = int(cfg.get("load_test_timeout_s", 120))
        self._p99_threshold = float(cfg.get("p99_alert_threshold_ms", 2000))

    def run(
        self,
        endpoint: str,
        expected_rps: int,
        test_duration_seconds: int,
    ) -> dict[str, Any]:
        start = time.time()
        result = subprocess.run(
            [
                "locust",
                "--headless",
                "--host", endpoint,
                "--users", str(expected_rps),
                "--spawn-rate", str(expected_rps),
                "--run-time", f"{test_duration_seconds}s",
                "--csv", "-",
            ],
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )

        p50, p95, p99, rps, error_rate = self._parse_csv(result.stdout)
        duration_ms = int((time.time() - start) * 1000)
        p99_exceeds = p99 > self._p99_threshold

        self._db.save_test_run(
            repo="load-test",
            run_type="load_test",
            passed=0,
            failed=0,
            coverage_pct=0.0,
            duration_ms=duration_ms,
            triggered_by="manual",
        )

        if p99_exceeds:
            enqueue_optimization(endpoint=endpoint, p99_ms=p99)
            logger.warning(
                "p99_threshold_exceeded",
                endpoint=endpoint,
                p99_ms=p99,
                threshold=self._p99_threshold,
            )

        return {
            "endpoint": endpoint,
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "rps": rps,
            "error_rate": error_rate,
            "duration_ms": duration_ms,
            "p99_exceeds_threshold": p99_exceeds,
        }

    # ------------------------------------------------------------------

    def _parse_csv(self, stdout: str) -> tuple[float, float, float, float, float]:
        """Return (p50, p95, p99, rps, error_rate) from Locust CSV stdout."""
        try:
            reader = csv.reader(io.StringIO(stdout.strip()))
            rows = list(reader)
            # Skip header row; take first data row
            for row in rows[1:]:
                if not row or not row[0].strip():
                    continue
                requests = float(row[_COL_REQUESTS]) if row[_COL_REQUESTS] else 1
                failures = float(row[_COL_FAILURES]) if row[_COL_FAILURES] else 0
                return (
                    float(row[_COL_P50]),
                    float(row[_COL_P95]),
                    float(row[_COL_P99]),
                    float(row[_COL_RPS]),
                    failures / max(requests, 1),
                )
        except (IndexError, ValueError, TypeError) as exc:
            logger.warning("locust_csv_parse_failed", error=str(exc))
        return 0.0, 0.0, 0.0, 0.0, 0.0
