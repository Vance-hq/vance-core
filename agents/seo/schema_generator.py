"""
Schema markup generator — produces and injects JSON-LD for 5 schema types.

Types: LocalBusiness, Service, FAQ, Review, HowTo
Output: inject via CMS API or commit to repo as a <script> block.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

logger = get_logger(__name__)

_VALID_TYPES = {"LocalBusiness", "Service", "FAQ", "Review", "HowTo"}

_SCHEMA_SYSTEM = """You are a schema markup specialist. Generate valid JSON-LD structured data.

Rules:
- Always include "@context": "https://schema.org" and "@type".
- Use real values from the business context provided.
- For LocalBusiness: include name, address (PostalAddress), telephone, url, openingHours.
- For Service: include name, provider, areaServed, description.
- For Review: include itemReviewed, reviewRating, author, reviewBody.
- For HowTo: include name, step array with HowToStep objects.
- Output only the JSON object — no explanation, no markdown fences.
"""

_BUSINESS_DEFAULTS: dict[str, dict[str, Any]] = {
    "trusted_plumbing": {
        "name": "Trusted Plumbing",
        "telephone": "(512) 555-0100",
        "url": "https://trustedplumbing.com",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "123 Main St",
            "addressLocality": "Austin",
            "addressRegion": "TX",
            "postalCode": "78701",
            "addressCountry": "US",
        },
        "priceRange": "$$",
        "openingHours": "Mo-Fr 08:00-18:00",
    },
    "localoutrank": {
        "name": "LocalOutRank",
        "telephone": "(512) 555-0200",
        "url": "https://localoutrank.com",
    },
    "oneserv": {
        "name": "OneServ",
        "url": "https://oneserv.com",
    },
    "starpio": {
        "name": "Starpio",
        "url": "https://starpio.com",
    },
}

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class SchemaGenerator:

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    def generate(
        self,
        schema_type: str,
        product: str,
        page_url: str,
        commit: bool = False,
        # FAQ-specific
        faqs: list[dict[str, str]] | None = None,
        # HowTo/Service/Review-specific
        page_title: str = "",
        page_content: str = "",
    ) -> dict[str, Any]:
        if schema_type not in _VALID_TYPES:
            return {"error": f"schema_type must be one of: {', '.join(sorted(_VALID_TYPES))}"}

        if schema_type == "FAQ" and faqs:
            json_ld = self._build_faq(faqs)
        elif schema_type == "LocalBusiness":
            json_ld = self._build_local_business(product)
        else:
            json_ld = self._generate_via_llm(
                schema_type=schema_type,
                product=product,
                page_url=page_url,
                page_title=page_title,
                page_content=page_content,
            )

        result: dict[str, Any] = {
            "schema_type": schema_type,
            "product": product,
            "page_url": page_url,
            "json_ld": json.dumps(json_ld),
        }

        if commit:
            committed = self._commit(product, page_url, schema_type, json_ld)
            result["committed"] = committed

        return result

    # ------------------------------------------------------------------

    def _build_local_business(self, product: str) -> dict[str, Any]:
        biz = _BUSINESS_DEFAULTS.get(product, {})
        schema: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
        }
        schema.update(biz)
        return schema

    def _build_faq(self, faqs: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": faq["question"],
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": faq["answer"],
                    },
                }
                for faq in faqs
            ],
        }

    def _generate_via_llm(
        self,
        schema_type: str,
        product: str,
        page_url: str,
        page_title: str,
        page_content: str,
    ) -> dict[str, Any]:
        biz_context = json.dumps(_BUSINESS_DEFAULTS.get(product, {"name": product}), indent=2)
        prompt = (
            f"Schema type: {schema_type}\n"
            f"Product: {product}\n"
            f"Page URL: {page_url}\n"
            f"Page title: {page_title}\n"
            f"Business context:\n{biz_context}\n"
            + (f"\nPage content (first 500 chars):\n{page_content[:500]}" if page_content else "")
            + "\n\nGenerate the JSON-LD schema."
        )
        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SCHEMA_SYSTEM,
            max_tokens=600,
            metadata={"caller": f"seo.schema_generator.{schema_type}"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            return json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("schema_parse_failed", type=schema_type, raw_preview=raw[:80])
            return {
                "@context": "https://schema.org",
                "@type": schema_type,
                "name": product,
                "url": page_url,
            }

    def _commit(
        self,
        product: str,
        page_url: str,
        schema_type: str,
        schema: dict[str, Any],
    ) -> bool:
        product_cfg = self._cfg.get("products", {}).get(product, {})
        repo_path = product_cfg.get("repo_path", ".")

        slug = re.sub(r"[^a-z0-9]+", "-", page_url.lower().split("//")[-1]).strip("-")[:60]
        schema_dir = Path(repo_path) / "schema"
        try:
            schema_dir.mkdir(parents=True, exist_ok=True)
            filepath = schema_dir / f"{slug}-{schema_type.lower()}.json"
            script_block = f'<script type="application/ld+json">\n{json.dumps(schema, indent=2)}\n</script>'
            filepath.write_text(script_block)

            result = subprocess.run(
                ["git", "add", str(filepath)],
                cwd=repo_path, capture_output=True, text=True,
            )
            if result.returncode == 0:
                commit = subprocess.run(
                    ["git", "commit", "-m", f"schema({product}): {schema_type} for {slug}"],
                    cwd=repo_path, capture_output=True, text=True,
                )
                return commit.returncode == 0
        except Exception as exc:
            logger.warning("schema_commit_failed", error=str(exc))
        return False
