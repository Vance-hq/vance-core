"""
CompetitorMonitor — weekly deep scan per product.

Checks: pricing, features, blog, job postings, G2/Capterra reviews.
LLM synthesises delta and recommended response.
Surfaces significant changes to the strategy agent.
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ResearchDB

logger = get_logger(__name__)

_MONITOR_SYSTEM = (
    "You are a competitive intelligence analyst. Given recent search results about a competitor, "
    "determine if anything significant changed (pricing, features, funding, product direction, "
    "job posting signals). Reply with JSON only: "
    "{\"changes_detected\": bool, \"summary\": str, \"recommended_response\": str}. "
    "Set changes_detected=false if nothing material changed."
)

_SEARCH_QUERIES = [
    "{competitor} pricing 2024 2025",
    "{competitor} new features announcement",
    "{competitor} job postings engineering",
    "{competitor} reviews G2 Capterra",
    "{competitor} funding news acquisition",
]


def web_search(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    from shared.search import search as _search
    try:
        return _search(query, num_results=num_results)
    except Exception as exc:
        logger.warning("web_search_failed", query=query, error=str(exc))
        return []


def enqueue_strategy_signal(
    product: str,
    competitor: str,
    summary: str,
    recommended_response: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="strategy",
            payload={
                "action": "competitor_signal",
                "product": product,
                "competitor": competitor,
                "summary": summary,
                "recommended_response": recommended_response,
                "source": "research",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_strategy_signal_failed", product=product, error=str(exc))


class CompetitorMonitor:

    def __init__(self, db: ResearchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        competitors: list[str] = prod_cfg.get("competitors", [])
        snapshots = []
        changes_found = 0

        for competitor in competitors:
            result = self._scan_competitor(product=product, competitor=competitor)
            snapshots.append(result)
            if result["changes_detected"]:
                changes_found += 1
                enqueue_strategy_signal(
                    product=product,
                    competitor=competitor,
                    summary=result["summary"],
                    recommended_response=result["recommended_response"],
                )

        logger.info("competitor_monitor_complete", product=product, scanned=len(competitors), changes=changes_found)
        return {
            "product": product,
            "competitors_scanned": len(competitors),
            "changes_found": changes_found,
            "snapshots": snapshots,
        }

    def _scan_competitor(self, product: str, competitor: str) -> dict[str, Any]:
        results: list[dict] = []
        for query_template in _SEARCH_QUERIES:
            query = query_template.format(competitor=competitor)
            hits = web_search(query, num_results=3)
            results.extend(hits)

        search_text = "\n".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')}"
            for r in results[:15]
        )

        prompt = (
            f"Competitor: {competitor}\n"
            f"Product we're monitoring for: {product}\n\n"
            f"Recent search results:\n{search_text or '(no results)'}"
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_MONITOR_SYSTEM,
            max_tokens=512,
        )
        raw = resp.content[0].text.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"changes_detected": False, "summary": raw[:200], "recommended_response": ""}

        changes_detected = bool(parsed.get("changes_detected", False))
        summary = parsed.get("summary", "")
        recommended_response = parsed.get("recommended_response", "")

        self._db.save_snapshot(
            product=product,
            competitor=competitor,
            changes_detected=changes_detected,
            summary=summary,
            raw_content=search_text[:2000],
        )

        return {
            "competitor": competitor,
            "changes_detected": changes_detected,
            "summary": summary,
            "recommended_response": recommended_response,
        }
