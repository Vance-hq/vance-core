"""
Viral piece creator — fast-path content generation timed to a trend.

Target: hook + 3 talking points + CTA in under 60 seconds.
Skips content calendar — publishes immediately within the opportunity window.

Platform formats:
  twitter   → thread (hook + supporting tweets)
  tiktok    → short video script (hook + 3 beats + CTA)
  linkedin  → hot take post (opinion-forward, data or story backed)
"""

from __future__ import annotations

import pathlib
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ViralDB

_FRAMEWORKS_MD = (
    pathlib.Path(__file__).parent.parent / "marketing" / "prompts" / "frameworks.md"
).read_text()

logger = get_logger(__name__)

_TWITTER_SYSTEM = """You are Dutch — a contractor who built software. Write a viral Twitter thread.

Format EXACTLY:
HOOK: [one punchy tweet ≤200 chars — make someone stop scrolling]

POINT1: [supporting tweet ≤280 chars — specific fact or observation]

POINT2: [supporting tweet ≤280 chars — practical implication or example]

POINT3: [supporting tweet ≤280 chars — the thing most people get wrong]

CTA: [closing tweet ≤280 chars — where to go or what to do next]

Rules: no hashtags, no "thread 🧵", no exclamation marks, short sentences.
"""

_TIKTOK_SYSTEM = """You are Dutch — a contractor who built software. Write a TikTok/short video script.

Format EXACTLY:
HOOK: [first 3 seconds — say this on camera to stop the scroll, ≤15 words]

POINT1: [beat 1 — 10-15 seconds of content, what happened or what you found]

POINT2: [beat 2 — 10-15 seconds, the specific detail that matters]

POINT3: [beat 3 — 10-15 seconds, what to actually do about it]

CTA: [5 seconds — one action: follow, check link in bio, or comment with a question]

Rules: conversational, direct, first person. No corporate speak. Each beat is one clear idea.
"""

_LINKEDIN_SYSTEM = """You are Dutch — a contractor who built software. Write a viral LinkedIn hot take.

Format EXACTLY:
HOOK: [opening line — a direct opinion or counterintuitive observation, ≤200 chars]

POINT1: [evidence or example from the real world that backs the hook]

POINT2: [the nuance — what most people miss or get backwards]

POINT3: [what actually works, based on direct experience]

CTA: [end with a direct question inviting real responses, or a strong statement of position]

Rules: 800-1200 chars total, first person, no corporate language, no buzzwords.
"""

_FORMAT_MAP = {
    "twitter": "thread",
    "tiktok": "script",
    "linkedin": "hot_take",
    "facebook": "hot_take",
}

_SYSTEM_MAP = {
    "twitter": _TWITTER_SYSTEM,
    "tiktok": _TIKTOK_SYSTEM,
    "linkedin": _LINKEDIN_SYSTEM,
    "facebook": _LINKEDIN_SYSTEM,
}


class PieceCreator:

    def __init__(self, db: ViralDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def create(
        self,
        trend_id: str,
        trend_topic: str,
        product: str,
        platform: str,
        opportunity_window_hours: int,
    ) -> dict[str, Any]:
        base_system = _SYSTEM_MAP.get(platform, _TWITTER_SYSTEM)
        system = (
            base_system
            + "\n\n## Copywriting Frameworks Reference\n\n" + _FRAMEWORKS_MD
            + "\n\nActive framework_mode: viral"
        )
        fmt = _FORMAT_MAP.get(platform, "thread")

        raw = llm.complete(
            messages=[{
                "role": "user",
                "content": (
                    f"Product: {product}\n"
                    f"Trend topic: {trend_topic}\n"
                    f"Opportunity window: {opportunity_window_hours} hours\n\n"
                    "Write the content now. Be specific to the trend — don't be generic."
                ),
            }],
            system=system,
            max_tokens=600,
            metadata={"caller": f"viral.piece_creator.{platform}", "framework_mode": "viral"},
        ).content[0].text.strip()

        hook = self._extract_section(raw, "HOOK")
        content = self._assemble_content(raw, platform)

        piece_id = self._db.save_viral_piece(
            trend_id=trend_id,
            product=product,
            platform=platform,
            content=content,
            hook=hook,
        )

        logger.info(
            "viral_piece_created",
            piece_id=piece_id,
            platform=platform,
            product=product,
            trend_topic=trend_topic,
        )

        return {
            "piece_id": piece_id,
            "platform": platform,
            "format": fmt,
            "hook": hook,
            "content": content,
            "trend_topic": trend_topic,
            "opportunity_window_hours": opportunity_window_hours,
        }

    # ------------------------------------------------------------------

    def _extract_section(self, raw: str, label: str) -> str:
        import re
        pattern = re.compile(rf"{label}:\s*(.+?)(?=POINT\d+:|CTA:|$)", re.DOTALL | re.IGNORECASE)
        match = pattern.search(raw)
        return match.group(1).strip() if match else raw.split("\n")[0].strip()

    def _assemble_content(self, raw: str, platform: str) -> str:
        if platform == "twitter":
            # Reassemble as a thread with separators
            import re
            parts = re.split(r"(?:HOOK|POINT\d+|CTA):\s*", raw, flags=re.IGNORECASE)
            tweets = [p.strip() for p in parts if p.strip()]
            return "\n---\n".join(tweets)
        return raw
