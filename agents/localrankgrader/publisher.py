"""
Monthly SEO publisher — generates anonymised GBP score landing pages.

Produces JSON output files at GRADER_SEO_OUTPUT_DIR.
One file per city+industry combination.
Format: "Average GBP Score for [Industry] in [City]: X/100"
These pages rank for "[industry] Google Business Profile score [city]" searches.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date
from typing import Any

from shared.logger import get_logger

from .db import GraderDB

logger = get_logger(__name__)

_DEFAULT_OUTPUT_DIR = os.getenv("GRADER_SEO_OUTPUT_DIR", "/tmp/grader_seo_pages")


class SEOPublisher:
    def __init__(self, db: GraderDB) -> None:
        self._db = db

    def publish_monthly(self) -> dict[str, Any]:
        """
        Aggregate last 30 days of audit data (anonymised) and write JSON page specs.
        Returns metadata about pages generated.
        """
        rows = self._db.recent_audits_for_seo(days=30)
        if not rows:
            logger.info("seo_publisher_no_data")
            return {"pages_generated": 0}

        grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
        for row in rows:
            industry = self._normalize_industry(row.get("types") or "")
            city = self._extract_city(row.get("address") or "")
            if industry and city:
                grouped[(industry, city)].append(int(row.get("overall_score") or 0))

        os.makedirs(_DEFAULT_OUTPUT_DIR, exist_ok=True)
        pages_written = 0
        for (industry, city), scores in grouped.items():
            if len(scores) < 3:  # Need at least 3 data points for a meaningful page
                continue
            avg = round(sum(scores) / len(scores), 1)
            page = self._build_page_spec(industry, city, avg, len(scores))
            slug = f"{industry.lower().replace(' ', '-')}-{city.lower().replace(' ', '-')}"
            path = os.path.join(_DEFAULT_OUTPUT_DIR, f"{slug}.json")
            with open(path, "w") as f:
                json.dump(page, f, indent=2)
            pages_written += 1

        logger.info("seo_pages_published", count=pages_written, output_dir=_DEFAULT_OUTPUT_DIR)
        return {
            "pages_generated": pages_written,
            "output_dir": _DEFAULT_OUTPUT_DIR,
            "month": date.today().strftime("%Y-%m"),
        }

    def _build_page_spec(self, industry: str, city: str, avg_score: float, sample_size: int) -> dict[str, Any]:
        slug = f"{industry.lower().replace(' ', '-')}-{city.lower().replace(' ', '-')}"
        return {
            "slug": slug,
            "title": f"Average Google Business Profile Score for {industry} in {city}: {avg_score}/100",
            "meta_description": (
                f"We analyzed {sample_size} {industry} businesses in {city}. "
                f"The average Google Business Profile score is {avg_score}/100. "
                f"See how your business compares — free audit at LocalRankGrader.com."
            ),
            "h1": f"{industry} Google Business Profile Scores in {city}",
            "body_intro": (
                f"We audited {sample_size} {industry} businesses in {city} on Google Maps. "
                f"The average GBP score was <strong>{avg_score}/100</strong>."
            ),
            "stats": {
                "industry": industry,
                "city": city,
                "avg_score": avg_score,
                "sample_size": sample_size,
            },
            "cta_text": f"See how your {industry} stacks up — free GBP audit",
            "cta_url": "https://localrankgrader.com",
            "schema_json_ld": {
                "@context": "https://schema.org",
                "@type": "WebPage",
                "name": f"{industry} GBP Score {city}",
                "description": f"Average Google Business Profile score for {industry} in {city}",
            },
            "generated_at": date.today().isoformat(),
        }

    def _normalize_industry(self, types_str: str) -> str:
        skip = {"point_of_interest", "establishment", "food", "store", "business"}
        parts = [t.replace("_", " ").title() for t in (types_str or "").split(",") if t and t not in skip]
        return parts[0] if parts else ""

    def _extract_city(self, address: str) -> str:
        parts = [p.strip() for p in address.split(",")]
        return parts[1] if len(parts) >= 2 else ""
