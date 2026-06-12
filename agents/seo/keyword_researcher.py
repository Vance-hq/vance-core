"""
Keyword researcher — GSC + SerpAPI + LLM clustering.

Process:
  1. SerpAPI: fetch SERP for seed topic, extract related searches + competitor URLs
  2. Web search: gather additional keyword ideas
  3. LLM: cluster keywords by intent, estimate volume/difficulty, map current rank
  4. Identify quick wins: position 11-20 (page 2) with meaningful volume
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from shared.llm.client import llm, web_search
from shared.logger import get_logger

from .db import SeoDB

logger = get_logger(__name__)

_CLUSTER_SYSTEM = """You are an SEO strategist. Given a seed topic, SERP data, and related searches,
cluster the keyword opportunities.

Output a JSON array of cluster objects:
  name     (string  — cluster theme)
  keywords (array of objects):
    keyword        (string)
    monthly_volume (int    — rough estimate based on SERP data and general knowledge)
    difficulty     (int    — 0-100, based on SERP competitor authority)
    current_rank   (int    — estimated current rank, use 0 if not ranking)

Return only valid JSON — no explanation, no markdown.
"""

_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)


class KeywordResearcher:

    def __init__(self, db: SeoDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg
        self._serp_api_key = cfg.get("serp_api_key", "")

    def research(
        self,
        product: str,
        seed_topic: str,
    ) -> dict[str, Any]:
        product_cfg = self._cfg.get("products", {}).get(product, {})
        domain = product_cfg.get("domain", "")

        # 1. SERP data
        serp_data = self._fetch_serp(seed_topic, domain)

        # 2. Additional web research
        related = web_search(f"{seed_topic} keyword opportunities", num_results=5)

        # 3. LLM clusters
        clusters = self._cluster(seed_topic, serp_data, related)

        # 4. Quick wins: p11-20
        quick_wins = [
            kw
            for cluster in clusters
            for kw in cluster.get("keywords", [])
            if 11 <= kw.get("current_rank", 0) <= 20
        ]

        # Save current rankings to DB
        for cluster in clusters:
            for kw in cluster.get("keywords", []):
                rank = kw.get("current_rank", 0)
                if rank > 0:
                    self._db.save_keyword_ranking(
                        product=product,
                        keyword=kw["keyword"],
                        rank=rank,
                        url=f"https://{domain}",
                    )

        logger.info(
            "keyword_research_complete",
            product=product,
            seed=seed_topic,
            clusters=len(clusters),
            quick_wins=len(quick_wins),
        )

        return {
            "product": product,
            "seed_topic": seed_topic,
            "clusters": clusters,
            "quick_wins": quick_wins,
        }

    # ------------------------------------------------------------------

    def _fetch_serp(self, query: str, domain: str) -> dict[str, Any]:
        if not self._serp_api_key:
            return {"organic_results": [], "related_searches": []}
        try:
            resp = httpx.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": self._serp_api_key,
                    "engine": "google",
                    "num": 20,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("serp_api_failed", query=query, error=str(exc))
        return {"organic_results": [], "related_searches": []}

    def _cluster(
        self,
        seed: str,
        serp_data: dict[str, Any],
        related: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        organic = serp_data.get("organic_results", [])[:10]
        rel_searches = serp_data.get("related_searches", [])
        extra_titles = [r.get("title", "") for r in related[:5]]

        context = (
            f"Seed topic: {seed}\n\n"
            f"Top SERP results:\n" +
            "\n".join(f"  {r.get('position', '?')}. {r.get('title', '')} — {r.get('link', '')}"
                      for r in organic) +
            f"\n\nRelated searches: {', '.join(str(r) for r in rel_searches[:8])}\n"
            f"Additional context: {', '.join(extra_titles)}"
        )

        raw = llm.complete(
            messages=[{"role": "user", "content": context}],
            system=_CLUSTER_SYSTEM,
            max_tokens=1200,
            metadata={"caller": "seo.keyword_researcher"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            data = json.loads(match.group() if match else raw)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, AttributeError):
            logger.warning("keyword_cluster_parse_failed", raw_preview=raw[:100])
            return []
