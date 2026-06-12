"""
Landing page writer — generates 3 A/B variants per section, commits to repo.

Sections: hero | benefits | pricing | faq | cta
Dev agent handles actual deployment; this agent only produces and commits the files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ContentDB

logger = get_logger(__name__)

_VALID_SECTIONS = {"hero", "benefits", "pricing", "faq", "cta"}

_VARIANT_SYSTEM = """You are Dutch — a contractor who built software for contractors.

Write landing page copy. Voice rules:
- First person or direct second person ("you").
- Short sentences. Active voice. No corporate language.
- Every section contains one concrete, specific claim — not vague promises.
- No exclamation marks in hero or cta. No buzzwords.
- The copy must match the performance signal: if conversion is low, make the value clearer.
  If bounce is high, make the hook more specific. If heatmap shows ignoring a section, shorten it.

Output EXACTLY three variants labeled:
VARIANT_A:
[copy]

VARIANT_B:
[copy]

VARIANT_C:
[copy]
"""


class LandingWriter:

    def __init__(self, db: ContentDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def write(
        self,
        product: str,
        section: str,
        performance_signal: str,
    ) -> dict[str, Any]:
        if section not in _VALID_SECTIONS:
            return {"error": f"section must be one of: {', '.join(sorted(_VALID_SECTIONS))}"}

        raw = self._generate(product, section, performance_signal)
        variants = self._parse_variants(raw)

        # Save each variant as a separate piece and commit files
        committed = self._commit_variants(product, section, variants)

        return {
            "variants": variants,
            "section": section,
            "product": product,
            "committed": committed,
        }

    # ------------------------------------------------------------------

    def _generate(self, product: str, section: str, signal: str) -> str:
        prompt = (
            f"Product: {product}\n"
            f"Section to rewrite: {section}\n"
            f"Performance signal: {signal}\n\n"
            f"Generate 3 distinct variants for the {section} section. "
            "Each variant must test a meaningfully different angle or framing."
        )
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_VARIANT_SYSTEM,
            max_tokens=1200,
            metadata={"caller": "content.landing_writer"},
        ).content[0].text.strip()

    def _parse_variants(self, raw: str) -> list[str]:
        import re
        parts = re.split(r"VARIANT_[ABC]:\s*", raw, flags=re.IGNORECASE)
        variants = [p.strip() for p in parts if p.strip()]
        # Pad to exactly 3 if LLM returns fewer
        while len(variants) < 3:
            variants.append(variants[-1] if variants else "")
        return variants[:3]

    def _commit_variants(
        self,
        product: str,
        section: str,
        variants: list[str],
    ) -> bool:
        product_cfg = self._cfg.get("products", {}).get(product, {})
        repo_path = product_cfg.get("repo_path", ".")
        ab_dir = Path(repo_path) / "ab_tests" / section

        labels = ["a", "b", "c"]
        piece_ids = []

        for i, (variant, label) in enumerate(zip(variants, labels)):
            piece_id = self._db.save_piece(
                product=product,
                platform="landing_page",
                content_type=f"landing_{section}_variant_{label}",
                title=f"{product} {section} variant {label.upper()}",
                body=variant,
                status="ab_test",
            )
            piece_ids.append(piece_id)

            # Write variant file (only if repo path exists or is writable)
            try:
                ab_dir.mkdir(parents=True, exist_ok=True)
                filepath = ab_dir / f"variant_{label}.md"
                filepath.write_text(
                    f"---\nproduct: {product}\nsection: {section}\n"
                    f"variant: {label.upper()}\npiece_id: {piece_id}\n"
                    f"performance_signal: written\n---\n\n{variant}\n"
                )
            except OSError as exc:
                logger.warning("landing_write_file_failed", error=str(exc))

        # Attempt git commit
        try:
            result = subprocess.run(
                ["git", "add", str(ab_dir)],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                commit = subprocess.run(
                    ["git", "commit", "-m",
                     f"ab-test({product}): {section} — 3 variants"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                )
                committed = commit.returncode == 0
            else:
                committed = False
        except Exception as exc:
            logger.warning("landing_git_commit_failed", error=str(exc))
            committed = False

        logger.info(
            "landing_variants_generated",
            product=product,
            section=section,
            committed=committed,
            piece_ids=piece_ids,
        )
        return committed
