"""
A/B test analyzer — compares sequence variants after >= 200 sends.
Applies winning variant to all new enrollments.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from shared.llm.client import llm
from shared.logger import get_logger

if TYPE_CHECKING:
    from .db import ForgeDB

logger = get_logger(__name__)

_ANALYSIS_PROMPT = """
You are an email outreach expert analyzing A/B test results.

Sequence: {sequence_name}
Metric optimizing for: {metric}

Variant A — {field}: "{value_a}"
  Sends: {sends_a}  |  {metric}: {rate_a:.1%}

Variant B — {field}: "{value_b}"
  Sends: {sends_b}  |  {metric}: {rate_b:.1%}

Statistical confidence: {confidence:.0%}
Winner: Variant {winner}

Provide:
1. One sentence on WHY the winner outperformed
2. One specific recommendation to further improve {metric}

Be concrete and specific. Max 60 words total.
""".strip()


class SequenceOptimizer:
    def __init__(self, db: "ForgeDB", min_sends: int = 200) -> None:
        self._db = db
        self._min_sends = min_sends

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def optimize(self, sequence_id: str) -> dict[str, Any]:
        """Analyze open/reply test data; apply winner; return test result."""
        metrics = self._db.get_sequence_metrics(sequence_id)
        if metrics["sends"] < self._min_sends:
            return {
                "status": "insufficient_data",
                "sends": metrics["sends"],
                "required": self._min_sends,
            }

        sequence = self._db.get_sequence(sequence_id)
        if not sequence:
            raise ValueError(f"Sequence not found: {sequence_id}")

        open_tests = self._db.get_open_ab_tests(sequence_id)
        if not open_tests:
            # Auto-create a subject line test from step 1
            return self._create_subject_test(sequence_id, sequence)

        results = []
        for test in open_tests:
            result = self._resolve_test(test, sequence)
            results.append(result)

        return {"status": "resolved", "tests": results}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_test(self, test: dict[str, Any], sequence: dict[str, Any]) -> dict[str, Any]:
        sends = self._db.get_sends_for_sequence(str(test["sequence_id"]))
        variant_a = test["variant_a"]
        variant_b = test["variant_b"]
        metric = test["metric"]

        # Split sends by which variant was active at send time
        # Simplified: compare first half vs second half of sends (chronological)
        mid = len(sends) // 2
        group_a = sends[:mid]
        group_b = sends[mid:]

        rate_a = self._compute_metric(group_a, metric)
        rate_b = self._compute_metric(group_b, metric)

        winner = "A" if rate_a >= rate_b else "B"
        # Wilson confidence interval simplified to z-score diff
        total_a = len(group_a) or 1
        total_b = len(group_b) or 1
        confidence = min(
            abs(rate_a - rate_b) / (math.sqrt(rate_a * (1 - rate_a) / total_a + rate_b * (1 - rate_b) / total_b) + 1e-9) / 2.0,
            0.99,
        )

        analysis = self._llm_analysis(
            sequence_name=sequence["name"],
            metric=metric,
            field=variant_a.get("field", "subject"),
            value_a=variant_a.get("value", ""),
            value_b=variant_b.get("value", ""),
            sends_a=total_a,
            sends_b=total_b,
            rate_a=rate_a,
            rate_b=rate_b,
            winner=winner,
            confidence=confidence,
        )

        self._db.resolve_ab_test(str(test["id"]), winner, confidence, analysis)

        # Apply winner for new enrollments
        winning_variant = variant_a if winner == "A" else variant_b
        self._db.apply_sequence_variant(str(test["sequence_id"]), winning_variant)

        logger.info(
            "ab_test_resolved",
            test_id=str(test["id"]),
            winner=winner,
            confidence=round(confidence, 3),
            metric=metric,
        )
        return {
            "test_id": str(test["id"]),
            "winner": winner,
            "confidence": round(confidence, 3),
            "rate_a": round(rate_a, 3),
            "rate_b": round(rate_b, 3),
            "analysis": analysis,
        }

    def _compute_metric(self, sends: list[dict[str, Any]], metric: str) -> float:
        if not sends:
            return 0.0
        send_ids = [str(s["id"]) for s in sends]
        total = len(send_ids)
        if metric == "open_rate":
            opened = sum(1 for s in sends if self._db.get_open_count(str(s["id"])) > 0)
            return opened / total
        if metric == "reply_rate":
            replied = sum(1 for s in sends if s.get("status") not in ("PENDING", "SENT", "DELIVERED"))
            # Better: join with replies table — using send status as proxy here
            return replied / total
        return 0.0

    def _create_subject_test(self, sequence_id: str, sequence: dict[str, Any]) -> dict[str, Any]:
        steps = sequence.get("steps") or []
        if not steps:
            return {"status": "no_steps"}
        current_subject = steps[0].get("subject", "")
        # Generate an alternative subject via LLM
        try:
            alt = llm.complete(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Rewrite this cold email subject line to be shorter and more curiosity-driven "
                        f"(max 6 words, no punctuation):\n\n{current_subject}\n\nOutput ONLY the new subject."
                    ),
                }],
                max_tokens=20,
                metadata={"caller": "forge.optimizer.subject"},
            ).content[0].text.strip()
        except Exception:
            return {"status": "llm_failed"}

        test_id = self._db.create_ab_test(
            sequence_id=sequence_id,
            variant_a={"field": "subject", "value": current_subject},
            variant_b={"field": "subject", "value": alt},
            metric="open_rate",
        )
        logger.info("ab_test_created", test_id=test_id, sequence_id=sequence_id)
        return {"status": "test_created", "test_id": test_id, "variant_b_subject": alt}

    def _llm_analysis(self, **kwargs: Any) -> str:
        try:
            return llm.complete(
                messages=[{"role": "user", "content": _ANALYSIS_PROMPT.format(**kwargs)}],
                max_tokens=120,
                metadata={"caller": "forge.optimizer.analysis"},
            ).content[0].text.strip()
        except Exception as exc:
            logger.debug("optimizer_llm_failed", error=str(exc))
            return ""
