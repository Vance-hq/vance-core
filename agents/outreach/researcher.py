"""Contact researcher — web search + LLM brief synthesis."""

from __future__ import annotations

from typing import Any

from shared.llm.client import llm, web_search
from shared.logger import get_logger

logger = get_logger(__name__)

_BRIEF_SYSTEM = """You are a sales intelligence researcher.

Given raw web search results about a contact, synthesise a research brief for an outreach rep.

Output exactly 3-4 sentences covering:
1. What this person / company does specifically (not generic)
2. A recent development, pain, or opportunity worth mentioning
3. What to lead with in outreach (the angle most likely to resonate)
4. One thing to avoid (a topic, competitor, or assumption that would land badly)

Be concrete and specific. No filler. If data is thin, say so rather than fabricating.
"""

_PRODUCT_PERSONAS: dict[str, str] = {
    "starpio": "restaurant owners, agency owners, and local business operators managing reservations",
    "oneserv": "HVAC, plumbing, and electrical contractors with fewer than 20 employees",
    "localoutrank": "local businesses that rely on Google Maps visibility and organic local search",
    "trusted_plumbing": "local homeowners and property managers seeking trusted trade referrals",
}


class ContactResearcher:

    def research(
        self,
        name: str,
        company: str,
        product: str,
        website: str | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        """
        Research a contact and return a brief + raw search results.
        Stored by the caller in contacts.research_notes.
        """
        persona_context = _PRODUCT_PERSONAS.get(product, "")

        queries = [
            f"{name} {company} {role or ''} LinkedIn".strip(),
            f"{company} recent news {role or 'founder CEO owner'}".strip(),
        ]
        if website:
            queries.append(f"site:{website} about")

        snippets: list[str] = []
        for q in queries:
            try:
                results = web_search(q, num_results=3)
                snippets.extend(results)
            except Exception as exc:
                logger.warning("research_search_failed", query=q, error=str(exc))

        if not snippets:
            brief = f"No public data found for {name} at {company}. Proceed with generic outreach."
            return {"brief": brief, "snippets": []}

        raw_text = "\n\n".join(snippets[:9])
        prompt = (
            f"Contact: {name}, {role or 'unknown role'} at {company}\n"
            f"Our product targets: {persona_context}\n\n"
            f"Search results:\n{raw_text}"
        )

        brief = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_BRIEF_SYSTEM,
            max_tokens=300,
            metadata={"caller": "outreach.researcher"},
        ).content[0].text.strip()

        logger.info("contact_research_complete", name=name, company=company, brief_len=len(brief))
        return {"brief": brief, "snippets": snippets[:9]}
