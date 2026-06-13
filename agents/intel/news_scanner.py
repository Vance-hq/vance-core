"""NewsScanner — scan industry news and surface high-relevance signals to strategy."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

from .db import IntelDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a market intelligence analyst. Given news headlines and snippets about a product category, "
    "score each for relevance (1-10) to a SaaS founder, and extract a 1-sentence summary. "
    "Output JSON only: [{\"headline\": str, \"relevance\": int, \"summary\": str, \"url\": str}]"
)

_HIGH_RELEVANCE = 7


def _web_search(query: str, num: int = 5) -> list[dict[str, Any]]:
    try:
        from shared.search import search as _search
        return _search(query, num_results=num)
    except Exception as exc:
        logger.warning("web_search_failed", query=query, error=str(exc))
        return []


def _enqueue_strategy(product: str, signals: list[dict]) -> None:
    try:
        TaskQueue().push(
            agent="strategy",
            payload={"action": "market_signal", "product": product, "signals": signals, "source": "intel"},
        )
    except Exception as exc:
        logger.warning("enqueue_strategy_failed", error=str(exc))


class NewsScanner:

    def __init__(self, db: IntelDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        keywords = self._cfg.get("products", {}).get(product, {}).get("keywords", [])
        results: list[dict] = []
        for kw in keywords[:5]:
            hits = _web_search(f"{kw} news", num=5)
            results.extend(hits)

        if not results:
            return {"product": product, "signals_found": 0}

        snippets = "\n".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')} ({r.get('url', '')})"
            for r in results[:20]
        )
        resp = llm.complete(
            messages=[{"role": "user", "content": f"Product category keywords: {keywords}\n\nNews:\n{snippets}"}],
            system=_SYSTEM,
            max_tokens=1000,
        )
        raw = resp.content[0].text.strip()

        try:
            scored = json.loads(raw)
        except json.JSONDecodeError:
            match = __import__("re").search(r"\[.*\]", raw, __import__("re").DOTALL)
            scored = json.loads(match.group(0)) if match else []

        high_signals = []
        for item in scored:
            rel = int(item.get("relevance", 0))
            sig_id = self._db.save_signal(
                signal_type="news",
                headline=item.get("headline", "")[:500],
                product=product,
                relevance_score=rel,
                summary=item.get("summary", ""),
                source_url=item.get("url", ""),
            )
            if rel >= _HIGH_RELEVANCE:
                high_signals.append(item)

        if high_signals:
            _enqueue_strategy(product=product, signals=high_signals)

        logger.info("news_scan_complete", product=product, total=len(scored), high=len(high_signals))
        return {"product": product, "signals_found": len(scored), "high_relevance": len(high_signals)}
