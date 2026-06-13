"""CompetitorSocialMonitor — track competitor social activity and product announcements."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import IntelDB

logger = get_logger(__name__)

_SYSTEM = (
    "You are a competitive intelligence analyst monitoring social media. "
    "Given recent posts/activity for a competitor, identify: product announcements, "
    "pricing changes, or significant brand moves. "
    "Output JSON: {\"notable\": bool, \"findings\": [str], \"sentiment\": \"positive|negative|neutral\"}"
)


def _search_social(competitor: str, num: int = 8) -> list[dict[str, Any]]:
    try:
        from shared.search import search as _search
        return _search(f"{competitor} site:twitter.com OR site:linkedin.com announcement", num_results=num)
    except Exception as exc:
        logger.warning("social_search_failed", competitor=competitor, error=str(exc))
        return []


class CompetitorSocialMonitor:

    def __init__(self, db: IntelDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        competitors = self._cfg.get("products", {}).get(product, {}).get("competitors", [])
        notable_count = 0
        results = []

        for comp in competitors:
            hits = _search_social(comp)
            if not hits:
                continue

            snippets = "\n".join(f"- {h.get('title','')}: {h.get('snippet','')}" for h in hits[:10])
            resp = llm.complete(
                messages=[{"role": "user", "content": f"Competitor: {comp}\nPosts:\n{snippets}"}],
                system=_SYSTEM,
                max_tokens=400,
            )
            raw = resp.content[0].text.strip()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"notable": False, "findings": [], "sentiment": "neutral"}

            if parsed.get("notable"):
                notable_count += 1
                for finding in parsed.get("findings", []):
                    self._db.save_signal(
                        signal_type="social",
                        headline=finding[:500],
                        product=product,
                        competitor=comp,
                        relevance_score=8,
                        summary=finding[:200],
                    )

            results.append({"competitor": comp, "notable": parsed.get("notable", False), "findings": parsed.get("findings", [])})

        logger.info("social_monitor_complete", product=product, competitors=len(competitors), notable=notable_count)
        return {"product": product, "competitors_scanned": len(competitors), "notable_activity": notable_count, "results": results}
