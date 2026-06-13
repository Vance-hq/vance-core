"""ABTestManager — central A/B test registry with proportions z-test significance."""

from __future__ import annotations

import math
from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import AnalyticsDB

logger = get_logger(__name__)

_SIGNIFICANCE_LEVEL = 0.05
_MIN_SAMPLE_SIZE = 100


def _proportions_z_test(
    conversions_a: int,
    sample_a: int,
    conversions_b: int,
    sample_b: int,
) -> float | None:
    """Return two-tailed p-value for difference in proportions. Returns None if insufficient data."""
    if sample_a < _MIN_SAMPLE_SIZE or sample_b < _MIN_SAMPLE_SIZE:
        return None
    if conversions_a + conversions_b == 0:
        return None

    p_a = conversions_a / sample_a
    p_b = conversions_b / sample_b
    p_pool = (conversions_a + conversions_b) / (sample_a + sample_b)

    denominator = math.sqrt(p_pool * (1 - p_pool) * (1 / sample_a + 1 / sample_b))
    if denominator == 0:
        return None

    z = abs(p_a - p_b) / denominator
    # two-tailed p-value using complementary error function
    p_value = math.erfc(z / math.sqrt(2))
    return round(p_value, 6)


def _determine_winner(
    conversions_a: int,
    sample_a: int,
    conversions_b: int,
    sample_b: int,
    variant_a: str,
    variant_b: str,
) -> str | None:
    if sample_a == 0 or sample_b == 0:
        return None
    rate_a = conversions_a / sample_a
    rate_b = conversions_b / sample_b
    return variant_a if rate_a >= rate_b else variant_b


def _enqueue_winner(agent: str, product: str, test_name: str, winner: str) -> None:
    try:
        TaskQueue().push(
            agent=agent,
            payload={
                "action": "apply_ab_winner",
                "product": product,
                "test_name": test_name,
                "winner": winner,
                "source": "analytics",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_winner_failed", error=str(exc))


class ABTestManager:

    def __init__(self, db: AnalyticsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def register_test(
        self,
        agent: str,
        product: str,
        test_name: str,
        variant_a: str,
        variant_b: str,
        metric: str,
    ) -> dict[str, Any]:
        test_id = self._db.upsert_ab_test(
            agent=agent,
            product=product,
            test_name=test_name,
            variant_a=variant_a,
            variant_b=variant_b,
            metric=metric,
        )
        logger.info("ab_test_registered", agent=agent, product=product, test_name=test_name)
        return {"test_id": test_id, "status": "running"}

    def update_test(
        self,
        agent: str,
        product: str,
        test_name: str,
        sample_a: int,
        sample_b: int,
        conversions_a: int,
        conversions_b: int,
    ) -> dict[str, Any]:
        test = self._db.get_ab_test(agent=agent, product=product, test_name=test_name)
        if not test:
            return {"error": f"test not found: {test_name}"}

        p_value = _proportions_z_test(conversions_a, sample_a, conversions_b, sample_b)
        winner = None
        status = "running"

        if p_value is not None and p_value < _SIGNIFICANCE_LEVEL:
            winner = _determine_winner(
                conversions_a, sample_a, conversions_b, sample_b,
                test["variant_a"], test["variant_b"],
            )
            status = "significant"
            _enqueue_winner(agent=agent, product=product, test_name=test_name, winner=winner or "")

        self._db.record_ab_result(
            agent=agent,
            product=product,
            test_name=test_name,
            sample_a=sample_a,
            sample_b=sample_b,
            conversions_a=conversions_a,
            conversions_b=conversions_b,
            p_value=p_value,
            winner=winner,
            status=status,
        )

        logger.info("ab_test_updated", test_name=test_name, p_value=p_value, status=status)
        return {
            "test_name": test_name,
            "p_value": p_value,
            "winner": winner,
            "status": status,
            "significant": status == "significant",
        }

    def check_all_running(self) -> dict[str, Any]:
        tests = self._db.get_running_tests()
        evaluated = 0
        concluded = 0
        for t in tests:
            result = self.update_test(
                agent=t["agent"],
                product=t["product"],
                test_name=t["test_name"],
                sample_a=t["sample_size_a"],
                sample_b=t["sample_size_b"],
                conversions_a=t["conversions_a"],
                conversions_b=t["conversions_b"],
            )
            evaluated += 1
            if result.get("significant"):
                concluded += 1
        return {"running_tests_evaluated": evaluated, "newly_concluded": concluded}
