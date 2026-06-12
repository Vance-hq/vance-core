"""
Copy generator with framework-aware LLM prompting.

framework_mode drives which copywriting framework structures the output.
frameworks.md is loaded once at module level and injected into every LLM call
as additional system context.
"""

from __future__ import annotations

import pathlib
from typing import TypedDict

from shared.llm.client import llm
from shared.logger import get_logger

logger = get_logger(__name__)

_PROMPTS_DIR = pathlib.Path(__file__).parent / "prompts"
_FRAMEWORKS_MD = (_PROMPTS_DIR / "frameworks.md").read_text()
_EMAIL_SYSTEM = (_PROMPTS_DIR / "email_system.txt").read_text()

_FRAMEWORK_INSTRUCTION = """
Active framework_mode: {framework_mode}

Refer to the Framework Selection Logic table in the frameworks reference above.
Apply the indicated lead framework and secondary rules for this mode.
""".strip()


class CopyOutput(TypedDict):
    headline: str
    body: str
    cta: str
    framework_mode: str
    tone: str


def generate_copy(
    target_persona: str,
    product: str,
    goal: str,
    tone: str,
    sequence_position: int,
    framework_mode: str,
) -> CopyOutput:
    """Generate direct-response copy using the specified copywriting framework."""
    framework_block = _FRAMEWORK_INSTRUCTION.format(framework_mode=framework_mode)

    system = "\n\n".join([
        _EMAIL_SYSTEM,
        "---\n## Copywriting Frameworks Reference\n\n" + _FRAMEWORKS_MD,
        framework_block,
    ])

    prompt = (
        f"Target persona: {target_persona}\n"
        f"Product: {product}\n"
        f"Goal: {goal}\n"
        f"Tone: {tone}\n"
        f"Sequence position: {sequence_position}\n\n"
        "Write copy following the active framework_mode structure.\n"
        "Output JSON with keys: headline, body, cta\n"
        "Output only valid JSON — no markdown fences, no explanation."
    )

    raw = llm.complete(
        messages=[{"role": "user", "content": prompt}],
        system=system,
        max_tokens=600,
        metadata={"caller": "marketing.copy_generator", "framework_mode": framework_mode},
    )

    text = raw.content[0].text.strip() if raw.content else ""
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:]).rstrip("`").strip()

    try:
        import json
        parsed = json.loads(text)
        return CopyOutput(
            headline=parsed.get("headline", ""),
            body=parsed.get("body", ""),
            cta=parsed.get("cta", ""),
            framework_mode=framework_mode,
            tone=tone,
        )
    except Exception:
        logger.warning("copy_generator_parse_failed", framework_mode=framework_mode)
        return CopyOutput(
            headline="",
            body=text,
            cta="",
            framework_mode=framework_mode,
            tone=tone,
        )


def framework_mode_for_position(sequence_position: int) -> str:
    """Derive framework_mode from a generic sequence position (forge email steps)."""
    if sequence_position <= 2:
        return "cold_outreach"
    if sequence_position <= 4:
        return "sequence_early"
    return "sequence_offer"
