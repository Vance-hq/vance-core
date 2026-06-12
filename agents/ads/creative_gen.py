"""
Creative generator — LLM-driven ad copy for Google and Meta.

Outputs per call:
  - 5 headline variants  (≤30 chars for Google, ≤40 for Meta)
  - 5 description variants (≤90 chars for Google, ≤125 for Meta)
  - 3 CTA options
  - 3 image prompts (Meta only — forwarded to content agent for generation)
"""

from __future__ import annotations

import json
import re
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

logger = get_logger(__name__)

_GOOGLE_SYSTEM = """You are writing Google Search Ads for a B2B SaaS product.
Rules:
- Headlines: max 30 characters each, no punctuation at end, title case
- Descriptions: max 90 characters each, include a clear benefit and CTA
- CTAs: 2-3 words, action-oriented ("Start Free Trial", "See Your Score", "Book a Demo")
- No exclamation marks. No superlatives ("best", "amazing", "#1").
- Address a real business problem in concrete terms.
Output valid JSON only:
{"headlines": ["...", "...", "...", "...", "..."], "descriptions": ["...", "...", "...", "...", "..."], "ctas": ["...", "...", "..."]}"""

_META_SYSTEM = """You are writing Meta (Facebook/Instagram) Ads for a B2B SaaS product.
Rules:
- Headlines: max 40 characters, conversational, question or statement format
- Descriptions: max 125 characters, lead with the problem, end with the payoff
- CTAs: 2-4 words
- Image prompts: describe a realistic scene relevant to the business context (not stock-photo generic).
  Format: "A [subject] in [setting], [action/context], [lighting], professional photography"
- No exclamation marks. No buzzwords.
Output valid JSON only:
{"headlines": ["...", "...", "...", "...", "..."], "descriptions": ["...", "...", "...", "...", "..."], "ctas": ["...", "...", "..."], "image_prompts": ["...", "...", "..."]}"""

_PRODUCT_CONTEXT: dict[str, str] = {
    "starpio": "restaurant review management SaaS — helps owners respond to reviews and protect their reputation",
    "oneserv": "field service management SaaS for trades contractors — job dispatch, invoicing, scheduling",
    "localoutrank": "local SEO SaaS — Google Business Profile audit, rank tracking, citation management",
    "trusted_plumbing": "plumbing company — residential and commercial plumbing, emergency service, licensed & insured",
}

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class CreativeGenerator:

    def generate(
        self,
        product: str,
        platform: str,
        objective: str,
        audience: str,
        creative_brief: str,
    ) -> dict[str, Any]:
        """
        Returns a dict with keys:
          headlines (list[str]), descriptions (list[str]), ctas (list[str])
          image_prompts (list[str]) — Meta only
        """
        context = _PRODUCT_CONTEXT.get(product, product)
        system = _GOOGLE_SYSTEM if platform == "google" else _META_SYSTEM

        prompt = (
            f"Product: {product}\n"
            f"Context: {context}\n"
            f"Platform: {platform}\n"
            f"Objective: {objective}\n"
            f"Target audience: {audience}\n"
            f"Creative brief: {creative_brief}\n\n"
            "Generate the ad creative variants."
        )

        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=600,
            metadata={"caller": "ads.creative_gen"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            data = json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("creative_gen_json_parse_failed", raw_preview=raw[:100])
            data = {"headlines": [raw[:30]], "descriptions": [raw[:90]], "ctas": ["Learn More"]}

        return {
            "headlines": data.get("headlines", [])[:5],
            "descriptions": data.get("descriptions", [])[:5],
            "ctas": data.get("ctas", [])[:3],
            "image_prompts": data.get("image_prompts", [])[:3] if platform == "meta" else [],
        }

    def generate_for_rotation(
        self,
        product: str,
        platform: str,
        existing_headline: str,
        existing_description: str,
        weak_signal: str,
    ) -> dict[str, Any]:
        """Generate replacement creative for rotation. `weak_signal` explains why we're rotating."""
        context = _PRODUCT_CONTEXT.get(product, product)
        system = _GOOGLE_SYSTEM if platform == "google" else _META_SYSTEM

        prompt = (
            f"Product: {product} ({context})\n"
            f"Platform: {platform}\n"
            f"Current headline: {existing_headline}\n"
            f"Current description: {existing_description}\n"
            f"Why we're rotating: {weak_signal}\n\n"
            "Generate fresh variants that test a different angle or hook. "
            "Don't just rephrase — try a different problem/benefit framing."
        )
        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=500,
            metadata={"caller": "ads.creative_gen.rotation"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            data = json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            data = {"headlines": [raw[:30]], "descriptions": [raw[:90]], "ctas": ["Learn More"]}

        return {
            "headlines": data.get("headlines", [])[:5],
            "descriptions": data.get("descriptions", [])[:5],
            "ctas": data.get("ctas", [])[:3],
            "image_prompts": data.get("image_prompts", [])[:3] if platform == "meta" else [],
        }
