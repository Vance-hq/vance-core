"""
Citation auditor — NAP (Name, Address, Phone) consistency across directories.

Process:
  1. For each citation source: web search "{business name} site:{source}"
  2. LLM extracts NAP from search snippet
  3. Compare against canonical NAP from config
  4. Flag inconsistencies; note sources where listing not found
"""

from __future__ import annotations

import json
import re
from typing import Any

from shared.llm.client import llm, web_search
from shared.logger import get_logger

logger = get_logger(__name__)

_NAP_SYSTEM = """You are a local SEO specialist checking NAP (Name, Address, Phone) consistency.

Given search result snippets from multiple citation sources for a business,
compare each against the canonical NAP and identify inconsistencies.

Output a JSON object:
  inconsistencies (array) — each: { "source": "...", "field": "name|address|phone", "found": "...", "expected": "..." }
  consistent      (array) — list of source domains where NAP matched
  not_found       (array) — list of source domains where no listing was found

Return only valid JSON — no explanation.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class CitationAuditor:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def audit(self, business: str) -> dict[str, Any]:
        biz_cfg = self._cfg.get("businesses", {}).get(business, {})
        canonical = {
            "name": biz_cfg.get("name", ""),
            "address": biz_cfg.get("address", ""),
            "phone": biz_cfg.get("phone", ""),
        }
        sources = self._cfg.get("citation_sources", [])

        # Collect snippets from all sources
        source_snippets: dict[str, str] = {}
        for source in sources:
            results = web_search(
                f'"{canonical["name"]}" site:{source}',
                num_results=3,
            )
            if results:
                source_snippets[source] = "\n".join(
                    f"Title: {r.get('title', '')}\nSnippet: {r.get('content', '')}"
                    for r in results[:2]
                )

        # Single LLM call over all snippets
        analysis = self._analyze_all(canonical, sources, source_snippets)

        inconsistencies = analysis.get("inconsistencies", [])
        consistent = analysis.get("consistent", [])
        not_found = analysis.get("not_found", [])

        logger.info(
            "citation_audit_complete",
            business=business,
            sources_checked=len(sources),
            inconsistencies=len(inconsistencies),
            not_found=len(not_found),
        )

        return {
            "business": business,
            "sources_checked": len(sources),
            "inconsistencies": inconsistencies,
            "consistent": consistent,
            "not_found": not_found,
        }

    # ------------------------------------------------------------------

    def _analyze_all(
        self,
        canonical: dict[str, str],
        sources: list[str],
        snippets: dict[str, str],
    ) -> dict[str, Any]:
        snippet_text = "\n\n".join(
            f"=== {src} ===\n{snip}" for src, snip in snippets.items()
        ) or "No listings found."

        prompt = (
            f"Canonical NAP:\n"
            f"  Name: {canonical['name']}\n"
            f"  Address: {canonical['address']}\n"
            f"  Phone: {canonical['phone']}\n\n"
            f"Sources checked: {', '.join(sources)}\n\n"
            f"Search snippets:\n{snippet_text}\n\n"
            "Identify all NAP inconsistencies across these sources."
        )
        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_NAP_SYSTEM,
            max_tokens=600,
            metadata={"caller": "seo.citation_auditor"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            return json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("nap_parse_failed", raw_preview=raw[:80])
            return {"inconsistencies": [], "consistent": [], "not_found": sources}
