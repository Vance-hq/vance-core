"""SignalSynthesizer — daily cross-product signal synthesis identifying the single most important pattern."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import StrategyDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a strategic advisor to a SaaS founder. "
    "Given signals from multiple products and agents, identify the single most important "
    "thing happening across the business right now. "
    "Output JSON only: "
    "{\"insight\": str, \"products_affected\": [str], \"confidence\": float (0-1)}"
    "\n\nBe specific. One insight, not a summary of everything. "
    "Confidence reflects how clearly the data supports this insight."
)


class SignalSynthesizer:

    def __init__(self, db: StrategyDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def synthesize(self, products: list[str]) -> dict[str, Any]:
        all_signals: list[dict] = []
        for product in products:
            signals = self._db.list_signals(product=product, actioned=False, limit=15)
            for s in signals:
                s["_product"] = product
            all_signals.extend(signals)

        signal_lines = [
            f"- [{s['_product']}][{s['signal_type']}] {s['summary']}"
            for s in all_signals
        ] or ["No signals recorded yet across any product."]

        prompt = (
            f"Products: {', '.join(products)}\n\n"
            f"Recent signals ({len(all_signals)} total):\n"
            + "\n".join(signal_lines)
        )

        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=400,
            )
            raw = resp.content[0].text.strip()
            parsed = json.loads(raw)
            insight = parsed.get("insight", raw[:300])
            products_affected = parsed.get("products_affected", [])
            confidence = float(parsed.get("confidence", 0.5))
        except Exception as exc:
            logger.warning("signal_synthesizer_llm_failed", error=str(exc))
            insight = f"Signal synthesis unavailable. {len(all_signals)} signals collected across {len(products)} products."
            products_affected = products
            confidence = 0.0

        insight_id = self._db.save_insight(
            insight=insight,
            products_affected=products_affected,
            confidence=confidence,
        )

        self._deliver_via_voice(insight=insight, confidence=confidence)

        logger.info("signals_synthesized", products=len(products), signals=len(all_signals), confidence=confidence)
        return {
            "insight_id": insight_id,
            "insight": insight,
            "products_affected": products_affected,
            "confidence": confidence,
            "signals_processed": len(all_signals),
        }

    def _deliver_via_voice(self, insight: str, confidence: float) -> None:
        try:
            confidence_pct = int(confidence * 100)
            text = f"Strategic insight ({confidence_pct}% confidence): {insight}"
            TaskQueue().push(
                "voice",
                {
                    "action": "speak",
                    "text": text,
                    "priority": "high",
                    "source": "signal_synthesizer",
                },
            )
        except Exception as exc:
            logger.warning("signal_synthesizer_voice_failed", error=str(exc))
