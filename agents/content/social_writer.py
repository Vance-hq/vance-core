"""
Social post writer — platform-specific content for LinkedIn, Twitter/X, Facebook.

Formats:
  linkedin  — 800-1200 chars, long-form insight, ends with question or strong POV
  twitter   — thread: hook tweet + 5-7 supporting tweets (separator: ---)
  facebook  — conversational, community-focused, ends with engagement question
"""

from __future__ import annotations

import pathlib
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ContentDB

_FRAMEWORKS_MD = (
    pathlib.Path(__file__).parent.parent / "marketing" / "prompts" / "frameworks.md"
).read_text()

logger = get_logger(__name__)

_LINKEDIN_SYSTEM = """LinkedIn post — Dutch's voice.

Rules:
- 800-1200 characters total.
- Long-form insight. Not a listicle. Not a motivational post.
- First line is the hook — specific, concrete, earns the scroll.
- Share one real thing you learned or fixed. Be specific about the problem.
- End with a direct question OR a strong statement of position (your POV).
- No hashtags at the top. No emoji spam. No "I'm excited to share".
- First person. Short sentences. No corporate language.
"""

_TWITTER_SYSTEM = """Twitter/X thread — Dutch's voice.

Rules:
- Hook tweet: one punchy sentence that makes someone stop scrolling. ≤200 chars.
- 5-7 supporting tweets: each one builds on the last. Each ≤280 chars.
- Separate tweets with: ---
- Each tweet must work as a standalone sentence.
- No "thread 🧵" intro. Just the hook, then the thread.
- Numbers and specifics beat generalities.
- No hashtags. No filler like "Thread incoming".
"""

_FACEBOOK_SYSTEM = """Facebook post — Dutch's voice.

Rules:
- Conversational, direct. Written like you'd post to a local business group.
- Talk about a real problem or situation. Make it relatable.
- 200-500 characters.
- End with an engagement question that invites real answers, not just likes.
- No corporate language. No motivational fluff.
"""

_VALID_PLATFORMS = {"linkedin", "twitter", "facebook"}


class SocialWriter:

    def __init__(self, db: ContentDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def write(
        self,
        product: str,
        platform: str,
        topic: str,
        schedule: bool = False,
    ) -> dict[str, Any]:
        if platform not in _VALID_PLATFORMS:
            return {"error": f"platform must be one of: {', '.join(sorted(_VALID_PLATFORMS))}"}

        raw = self._generate(platform, product, topic)

        if platform == "twitter":
            tweets = self._parse_thread(raw)
            body = "\n---\n".join(tweets)
        else:
            body = self._trim_to_limits(raw, platform)

        piece_id = self._db.save_piece(
            product=product,
            platform=platform,
            content_type="social_post",
            title=f"{topic[:80]} — {platform}",
            body=body,
            status="draft",
        )

        result: dict[str, Any] = {
            "piece_id": piece_id,
            "platform": platform,
            "body": body,
            "status": "draft",
        }

        if platform == "twitter":
            result["tweets"] = tweets

        if schedule:
            scheduled = self._schedule(platform, body, product)
            result.update(scheduled)

        return result

    # ------------------------------------------------------------------

    def _generate(self, platform: str, product: str, topic: str) -> str:
        base_systems = {
            "linkedin": _LINKEDIN_SYSTEM,
            "twitter": _TWITTER_SYSTEM,
            "facebook": _FACEBOOK_SYSTEM,
        }
        system = (
            base_systems[platform]
            + "\n\n## Copywriting Frameworks Reference\n\n" + _FRAMEWORKS_MD
            + "\n\nActive framework_mode: viral"
        )
        prompt = (
            f"Product: {product}\n"
            f"Topic: {topic}\n\n"
            "Write the post now."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=800,
            metadata={"caller": f"content.social_writer.{platform}", "framework_mode": "viral"},
        ).content[0].text.strip()

    def _trim_to_limits(self, text: str, platform: str) -> str:
        if platform == "linkedin":
            min_c, max_c = 800, 1200
            if len(text) < min_c:
                return text  # LLM undershoot — return as-is
            return text[:max_c]
        if platform == "facebook":
            return text[:500]
        return text

    def _parse_thread(self, raw: str) -> list[str]:
        tweets = [t.strip() for t in raw.split("---") if t.strip()]
        # Ensure hook + at least 5 supporting
        if len(tweets) < 6:
            # Pad with a closing tweet if LLM returned fewer
            while len(tweets) < 6:
                tweets.append(tweets[-1] if tweets else "More to come.")
        return tweets[:8]

    def _schedule(self, platform: str, body: str, product: str) -> dict[str, Any]:
        """Schedule via Buffer API if token configured."""
        token = self._cfg.get("buffer_access_token")
        if not token:
            return {"scheduled": False, "reason": "buffer_access_token not configured"}

        try:
            import httpx as _httpx
            resp = _httpx.post(
                "https://api.bufferapp.com/1/updates/create.json",
                headers={"Authorization": f"Bearer {token}"},
                data={"text": body, "profile_ids[]": product},
                timeout=15,
            )
            if resp.status_code == 200:
                return {"scheduled": True, "buffer_id": resp.json().get("id")}
            return {"scheduled": False, "reason": f"Buffer returned {resp.status_code}"}
        except Exception as exc:
            logger.warning("social_schedule_failed", platform=platform, error=str(exc))
            return {"scheduled": False, "reason": str(exc)}
