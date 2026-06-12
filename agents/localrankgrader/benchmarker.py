"""
Competitive benchmarking — runs lightweight GBP audits on 3 local competitors.
Uses public Places API data only (no GBP Management API needed).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import httpx

from shared.config.settings import settings
from shared.logger import get_logger

from .db import GraderDB

logger = get_logger(__name__)

_PLACES_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
_DETAIL_FIELDS = "name,formatted_address,rating,user_ratings_total,photos,opening_hours,website,formatted_phone_number,editorial_summary,types"


class LocalBenchmarker:
    def __init__(self, db: GraderDB, competitor_count: int = 3, radius_km: int = 10) -> None:
        self._db = db
        self._count = competitor_count
        self._radius_m = radius_km * 1000

    def benchmark(
        self,
        audit_id: str,
        audit_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        place_id = audit_data.get("place_id")
        places_data = audit_data.get("raw_places_data", {})
        types = places_data.get("types") or []
        category = types[0] if types else "establishment"

        # Reuse geometry already fetched during audit; only call API if absent
        location = (places_data.get("geometry") or {}).get("location") or self._get_location(place_id)
        if not location:
            logger.warning("benchmarker_no_location", audit_id=audit_id)
            return []

        competitors = self._find_competitors(location, category, audit_data.get("place_id"))
        results = []
        for comp in competitors[:self._count]:
            comp_score, comp_cats = self._score_competitor(comp)
            bid = self._db.insert_benchmark(
                audit_id=audit_id,
                competitor_name=comp.get("name", "Unknown"),
                competitor_place_id=comp.get("place_id"),
                competitor_score=comp_score,
                competitor_address=comp.get("vicinity"),
                category_scores=comp_cats,
            )
            results.append({
                "id": bid,
                "competitor_name": comp.get("name"),
                "competitor_score": comp_score,
                "competitor_address": comp.get("vicinity"),
                "category_scores": comp_cats,
            })
            logger.info("benchmark_recorded", audit_id=audit_id, name=comp.get("name"), score=comp_score)

        return results

    def _get_location(self, place_id: str | None) -> dict[str, float] | None:
        if not place_id:
            return None
        try:
            resp = httpx.get(
                _PLACES_DETAILS_URL,
                params={"place_id": place_id, "fields": "geometry", "key": settings.GOOGLE_PLACES_API_KEY},
                timeout=10,
            )
            resp.raise_for_status()
            loc = resp.json().get("result", {}).get("geometry", {}).get("location")
            return loc  # {"lat": ..., "lng": ...}
        except Exception as exc:
            logger.error("benchmarker_geocode_failed", error=str(exc))
            return None

    def _find_competitors(
        self,
        location: dict[str, float],
        category: str,
        exclude_place_id: str | None,
    ) -> list[dict[str, Any]]:
        try:
            resp = httpx.get(
                _PLACES_NEARBY_URL,
                params={
                    "location": f"{location['lat']},{location['lng']}",
                    "radius": self._radius_m,
                    "type": category,
                    "key": settings.GOOGLE_PLACES_API_KEY,
                },
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            return [r for r in results if r.get("place_id") != exclude_place_id]
        except Exception as exc:
            logger.error("benchmarker_nearby_failed", error=str(exc))
            return []

    def _score_competitor(self, place: dict[str, Any]) -> tuple[int, dict[str, int]]:
        """Lightweight score using only public Nearby Search data (no additional API call)."""
        scores: dict[str, int] = {}

        # Completeness proxy (public fields only)
        comp = 0
        if place.get("name"):
            comp += 5
        if place.get("vicinity"):
            comp += 4
        if place.get("opening_hours"):
            comp += 4
        scores["completeness"] = min(comp, 25)

        # Photos
        photo_count = len(place.get("photos") or [])
        scores["photos"] = min(15 if photo_count >= 16 else (10 if photo_count >= 6 else (5 if photo_count >= 1 else 0)), 15)

        # Reviews
        count = place.get("user_ratings_total") or 0
        rating = place.get("rating") or 0.0
        cnt_score = 15 if count >= 100 else (10 if count >= 50 else (5 if count >= 10 else 0))
        rat_score = 5 if rating >= 4.5 else (3 if rating >= 4.0 else (1 if rating >= 3.5 else 0))
        scores["reviews"] = min(cnt_score + rat_score, 25)

        # Everything else: assume average (50% of max)
        scores["posts"] = 5
        scores["qa"] = 2
        scores["services"] = 2
        scores["keywords"] = 5
        scores["citations"] = 2

        overall = min(100, sum(scores.values()))
        return overall, scores
