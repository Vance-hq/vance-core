"""
MarketSignalScan — daily scan for industry signals.

Sources: web search (Google News, Reddit, industry keywords).
Relevance scored 0-10 by LLM. Signals >= 7 queued to reporting agent.
"""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ResearchDB

logger = get_logger(__name__)

_RELEVANCE_THRESHOLD = 7

_SCORE_SYSTEM = (
    "You are a market intelligence analyst. Score the relevance of a news headline "
    "to the given SaaS product on a scale of 0-10. "
    "10 = directly impacts the product's market or customers. "
    "0 = completely unrelated. Reply with a single integer only."
)


def web_search(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    from shared.search import search as _search
    try:
        return _search(query, num_results=num_results)
    except Exception as exc:
        logger.warning("web_search_failed", query=query, error=str(exc))
        return []


def enqueue_reporting_signal(
    product: str,
    headline: str,
    source: str,
    relevance_score: int,
    url: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="reporting",
            payload={
                "action": "add_signal",
                "product": product,
                "headline": headline,
                "source": source,
                "relevance_score": relevance_score,
                "url": url,
            },
        )
    except Exception as exc:
        logger.warning("enqueue_reporting_failed", product=product, error=str(exc))


class MarketSignalScan:

    def __init__(self, db: ResearchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        keywords: list[str] = prod_cfg.get("keywords", [])
        product_name = prod_cfg.get("name", product)

        signals_saved = 0
        signals_queued = 0

        for keyword in keywords:
            results = web_search(f"{keyword} news", num_results=5)
            for hit in results:
                headline = hit.get("title", "")
                url = hit.get("url", "")
                snippet = hit.get("snippet", "")
                if not headline:
                    continue

                score = self._score_relevance(
                    product_name=product_name,
                    keyword=keyword,
                    headline=headline,
                    snippet=snippet,
                )

                if score >= _RELEVANCE_THRESHOLD:
                    self._db.save_signal(
                        product=product,
                        source="web_search",
                        headline=headline,
                        relevance_score=score,
                        url=url,
                    )
                    enqueue_reporting_signal(
                        product=product,
                        headline=headline,
                        source="web_search",
                        relevance_score=score,
                        url=url,
                    )
                    signals_saved += 1
                    signals_queued += 1

        logger.info("market_signal_scan_complete", product=product, saved=signals_saved)
        return {
            "product": product,
            "keywords_scanned": len(keywords),
            "signals_saved": signals_saved,
            "signals_queued": signals_queued,
        }

    def _score_relevance(
        self,
        product_name: str,
        keyword: str,
        headline: str,
        snippet: str,
    ) -> int:
        prompt = (
            f"Product: {product_name}\n"
            f"Keyword context: {keyword}\n"
            f"Headline: {headline}\n"
            f"Snippet: {snippet}\n\n"
            "Score relevance 0-10:"
        )
        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SCORE_SYSTEM,
            max_tokens=8,
        )
        raw = resp.content[0].text.strip()
        try:
            return max(0, min(10, int(raw)))
        except (ValueError, TypeError):
            return 0
