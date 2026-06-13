"""Context retriever — answer 'what have we done about X' via decision_log search."""

from __future__ import annotations

from typing import Any

from shared.logger import get_logger

from .embedder import embed

logger = get_logger(__name__)


class ContextRetriever:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def retrieve(self, query: str, product: str = "", limit: int = 5) -> dict[str, Any]:
        embedding = embed(query)

        if embedding:
            results = self._db.search_decisions(embedding=embedding, product=product, limit=limit)
            method = "semantic"
        else:
            results = self._db.list_recent_decisions(days=90, product=product, limit=limit)
            method = "recency"

        formatted = [
            f"{r['agent']}.{r['action']}"
            + (f" [{r['product']}]" if r.get("product") else "")
            + f": {r.get('intent', '')} → {r.get('outcome', '')}"
            for r in results
        ]

        logger.info("context_retrieved", query=query, count=len(results), method=method)
        return {
            "query": query,
            "product": product,
            "results": results,
            "formatted": formatted,
            "method": method,
            "count": len(results),
        }
