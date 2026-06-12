"""
FeatureGapAnalysis — quarterly identification of features competitors have that we don't.

Pulls competitor feature lists via web search + G2 profiles.
LLM compares to current product feature set.
Gap list ranked by: customer demand + competitor coverage + estimated build effort.
Top 3 gaps enqueued to dev agent as feature proposals.
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ResearchDB

logger = get_logger(__name__)

_GAP_SYSTEM = (
    "You are a product manager performing competitive feature gap analysis. "
    "Given competitor feature descriptions and a current product feature set, "
    "identify features the competitors have that the product does NOT have. "
    "For each gap, estimate customer_demand_score (1-10) and effort (low/medium/high). "
    "Reply with JSON array only: "
    "[{\"feature\": str, \"competitor_coverage\": int, "
    "\"customer_demand_score\": int, \"effort\": \"low\"|\"medium\"|\"high\"}]. "
    "Do NOT include features already in the existing feature set."
)


def web_search(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    from shared.search import search as _search
    try:
        return _search(query, num_results=num_results)
    except Exception as exc:
        logger.warning("web_search_failed", query=query, error=str(exc))
        return []


def enqueue_dev_proposal(
    product: str,
    feature: str,
    competitor_coverage: int,
    customer_demand_score: int,
    effort: str,
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="dev",
            payload={
                "action": "feature_proposal",
                "product": product,
                "feature": feature,
                "competitor_coverage": competitor_coverage,
                "customer_demand_score": customer_demand_score,
                "effort": effort,
                "source": "research",
            },
            priority=4,
        )
    except Exception as exc:
        logger.warning("enqueue_dev_proposal_failed", product=product, feature=feature, error=str(exc))


class FeatureGapAnalysis:

    def __init__(self, db: ResearchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        competitors: list[str] = prod_cfg.get("competitors", [])
        existing_features: list[str] = prod_cfg.get("feature_set", [])
        product_name = prod_cfg.get("name", product)

        competitor_snippets: list[str] = []
        for competitor in competitors:
            hits = web_search(f"{competitor} features list pricing", num_results=5)
            hits += web_search(f"site:g2.com {competitor} features", num_results=3)
            for hit in hits:
                snippet = hit.get("snippet", "")
                title = hit.get("title", "")
                if snippet or title:
                    competitor_snippets.append(f"{competitor}: {title} — {snippet}")

        prompt = (
            f"Product: {product_name}\n"
            f"Existing features: {', '.join(existing_features)}\n\n"
            f"Competitor feature evidence:\n"
            + "\n".join(competitor_snippets[:30] or ["(no data found)"])
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_GAP_SYSTEM,
            max_tokens=1024,
        )
        raw = resp.content[0].text.strip()

        try:
            gaps: list[dict] = json.loads(raw)
            if not isinstance(gaps, list):
                gaps = []
        except json.JSONDecodeError:
            gaps = []

        # Filter out features already in the existing set
        gaps = [
            g for g in gaps
            if g.get("feature", "").lower() not in {f.lower() for f in existing_features}
        ]

        # Save all gaps to DB
        for gap in gaps:
            self._db.save_feature_gap(
                product=product,
                feature=gap.get("feature", ""),
                competitor_coverage=int(gap.get("competitor_coverage", 0)),
                customer_demand_score=int(gap.get("customer_demand_score", 0)),
            )

        # Enqueue top 3 to dev agent (ranked by customer demand score)
        top_gaps = sorted(gaps, key=lambda g: g.get("customer_demand_score", 0), reverse=True)[:3]
        for gap in top_gaps:
            enqueue_dev_proposal(
                product=product,
                feature=gap.get("feature", ""),
                competitor_coverage=int(gap.get("competitor_coverage", 0)),
                customer_demand_score=int(gap.get("customer_demand_score", 0)),
                effort=gap.get("effort", "medium"),
            )

        logger.info("feature_gap_analysis_complete", product=product, gaps=len(gaps), proposed=len(top_gaps))
        return {
            "product": product,
            "gaps_found": len(gaps),
            "gaps_proposed_to_dev": len(top_gaps),
            "gaps": gaps,
        }
