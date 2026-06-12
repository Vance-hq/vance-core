"""
Newsletter writer — weekly format, broadcast send via Resend.

Format per issue:
  LEAD:  one story (product update, customer win, or industry insight)
  ITEM1: short item
  ITEM2: short item
  CTA:   one clear call to action
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ContentDB

logger = get_logger(__name__)

_NEWSLETTER_SYSTEM = """You are Dutch. Write a weekly email newsletter.

Voice rules:
- First person, active voice. Short sentences. No corporate language.
- Each issue has one concrete, specific, actionable thing — not vague advice.
- Talk about what actually happened, what was built, what broke.
- No "I hope this finds you well". No filler. No fluff.

Format EXACTLY as:
LEAD: [1-3 sentence lead story]

ITEM1: [1-2 sentence short item]

ITEM2: [1-2 sentence short item]

CTA: [one clear action with a link placeholder if needed]
"""


class NewsletterWriter:

    def __init__(self, db: ContentDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def write(
        self,
        product: str,
        send: bool = False,
    ) -> dict[str, Any]:
        recent = self._db.get_recent_pieces(product=product, limit=5)

        raw = self._generate(product, recent)
        sections = self._parse(raw)

        body = self._render(sections)
        piece_id = self._db.save_piece(
            product=product,
            platform="email",
            content_type="newsletter",
            title=f"{product} newsletter",
            body=body,
            status="draft",
        )

        result: dict[str, Any] = {
            "piece_id": piece_id,
            "lead_story": sections["lead"],
            "short_items": [sections["item1"], sections["item2"]],
            "cta": sections["cta"],
            "status": "draft",
        }

        if send:
            sent = self._broadcast(product, body)
            result.update(sent)

        return result

    # ------------------------------------------------------------------

    def _generate(self, product: str, recent: list[dict[str, Any]]) -> str:
        context = "\n".join(
            f"- {p['title']} ({p['type']})" for p in recent[:5]
        )
        prompt = (
            f"Product: {product}\n"
            f"Recent content published:\n{context or 'None yet.'}\n\n"
            "Write this week's newsletter."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_NEWSLETTER_SYSTEM,
            max_tokens=500,
            metadata={"caller": "content.newsletter_writer"},
        ).content[0].text.strip()

    def _parse(self, raw: str) -> dict[str, str]:
        import re
        sections = {"lead": "", "item1": "", "item2": "", "cta": ""}
        patterns = {
            "lead": r"LEAD:\s*(.+?)(?=ITEM1:|ITEM2:|CTA:|$)",
            "item1": r"ITEM1:\s*(.+?)(?=ITEM2:|CTA:|$)",
            "item2": r"ITEM2:\s*(.+?)(?=CTA:|$)",
            "cta": r"CTA:\s*(.+?)$",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
            if match:
                sections[key] = match.group(1).strip()
        return sections

    def _render(self, sections: dict[str, str]) -> str:
        return (
            f"{sections['lead']}\n\n"
            f"{sections['item1']}\n\n"
            f"{sections['item2']}\n\n"
            f"{sections['cta']}"
        ).strip()

    def _broadcast(self, product: str, body: str) -> dict[str, Any]:
        """Send via Resend broadcast API."""
        api_key = self._cfg.get("resend_api_key", "")
        from_email = self._cfg.get("newsletter_from_email", "")
        from_name = self._cfg.get("newsletter_from_name", "Dutch")

        if not api_key or not from_email:
            return {"sent": False, "reason": "resend_api_key or newsletter_from_email not configured"}

        try:
            resp = httpx.post(
                "https://api.resend.com/broadcasts",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"{from_name} <{from_email}>",
                    "subject": f"{product} — weekly update",
                    "html": f"<pre>{body}</pre>",
                    "audience_id": product,
                },
                timeout=20,
            )
            if resp.status_code in (200, 201):
                broadcast_id = resp.json().get("id")
                logger.info("newsletter_broadcast_sent", product=product, broadcast_id=broadcast_id)
                return {"sent": True, "broadcast_id": broadcast_id}
            logger.warning("newsletter_broadcast_failed", status=resp.status_code)
            return {"sent": False, "reason": f"Resend returned {resp.status_code}"}
        except Exception as exc:
            logger.warning("newsletter_broadcast_error", error=str(exc))
            return {"sent": False, "reason": str(exc)}
