"""
GBP auditor — Google Places API + Playwright scraping + citation check.

Score breakdown (100 pts total):
  completeness  25  — name, address, phone, website, hours, description
  photos        15  — count score
  reviews       25  — count + rating + response rate
  posts         10  — last post date + 90-day frequency (Playwright)
  qa             5  — questions present + answered (Playwright)
  services       5  — service/product listings (Playwright)
  keywords      10  — primary keyword in name / description / categories
  citations      5  — NAP consistency across top directories (SearXNG)
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from shared.config.settings import settings
from shared.llm.client import web_search
from shared.logger import get_logger

logger = get_logger(__name__)

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", settings.PLAYWRIGHT_BROWSERS_PATH)

_PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
_PLACES_SEARCH_URL  = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_DETAIL_FIELDS = (
    "name,formatted_address,formatted_phone_number,website,opening_hours,"
    "rating,user_ratings_total,photos,types,editorial_summary,reviews,business_status,geometry"
)


class GBPAuditor:
    def __init__(self, score_weights: dict[str, int], citation_directories: list[str]) -> None:
        self._weights = score_weights
        self._directories = citation_directories

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def audit(
        self,
        business_name: str,
        place_id: str | None,
        address: str | None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        """Run the full audit and return structured results."""
        resolved_id, places_data = self._fetch_places_data(business_name, place_id, address)
        playwright_data = self._scrape_gbp_page(resolved_id) if resolved_id else {}
        nap_data = self._check_citations(
            business_name,
            places_data.get("formatted_phone_number"),
            places_data.get("formatted_address"),
        )

        scores, raw_scores = self._calculate_scores(places_data, playwright_data, nap_data, keyword)
        overall = min(100, sum(scores.values()))
        recommendations = self._build_recommendations(scores, raw_scores, places_data, playwright_data)

        return {
            "place_id": resolved_id,
            "address": places_data.get("formatted_address"),
            "overall_score": overall,
            "category_scores": scores,
            "raw_scores": raw_scores,
            "recommendations": recommendations,
            "raw_places_data": places_data,
            "playwright_data": playwright_data,
        }

    # ------------------------------------------------------------------
    # Places API
    # ------------------------------------------------------------------

    def _fetch_places_data(
        self,
        business_name: str,
        place_id: str | None,
        address: str | None,
    ) -> tuple[str | None, dict[str, Any]]:
        if not place_id:
            place_id = self._find_place_id(business_name, address)
        if not place_id:
            logger.warning("places_place_not_found", business=business_name)
            return None, {}

        try:
            resp = httpx.get(
                _PLACES_DETAILS_URL,
                params={"place_id": place_id, "fields": _DETAIL_FIELDS, "key": settings.GOOGLE_PLACES_API_KEY},
                timeout=15,
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            return place_id, result
        except Exception as exc:
            logger.error("places_details_error", place_id=place_id, error=str(exc))
            return place_id, {}

    def _find_place_id(self, business_name: str, address: str | None) -> str | None:
        query = f"{business_name} {address or ''}".strip()
        try:
            resp = httpx.get(
                _PLACES_SEARCH_URL,
                params={"query": query, "key": settings.GOOGLE_PLACES_API_KEY},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            return results[0]["place_id"] if results else None
        except Exception as exc:
            logger.error("places_search_error", query=query, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # Playwright scraping
    # ------------------------------------------------------------------

    def _scrape_gbp_page(self, place_id: str) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {}

        url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"
        data: dict[str, Any] = {
            "posts_count": 0,
            "last_post_days_ago": None,
            "qa_count": 0,
            "qa_answered": 0,
            "services_listed": False,
        }

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, timeout=30_000)

                try:
                    page.click('[aria-label="Accept all"]', timeout=3_000)
                except Exception:
                    pass

                page.wait_for_timeout(3_000)

                # Posts / Updates tab
                try:
                    updates_btn = page.locator('button[aria-label*="Updates"], button[aria-label*="Posts"]').first
                    if updates_btn.is_visible():
                        updates_btn.click()
                        page.wait_for_timeout(2_000)
                        post_items = page.locator('[data-post-id], .rlfl__post').all()
                        data["posts_count"] = len(post_items)
                        if post_items:
                            # Try to extract relative date from first post
                            first_post_text = post_items[0].inner_text()
                            data["last_post_days_ago"] = self._parse_relative_days(first_post_text)
                except Exception:
                    pass

                # Q&A section
                try:
                    qa_section = page.locator('[aria-label*="Questions"], [aria-label*="Q&A"]').first
                    if qa_section.is_visible():
                        qa_items = page.locator('.gws-localreviews__general-reviews-block').all()
                        data["qa_count"] = len(qa_items)
                        answered = page.locator('[aria-label*="Answer"]').count()
                        data["qa_answered"] = answered
                except Exception:
                    pass

                # Services / Menu
                try:
                    services_btn = page.locator(
                        'button[aria-label*="Services"], button[aria-label*="Menu"]'
                    ).first
                    data["services_listed"] = services_btn.is_visible()
                except Exception:
                    pass

                browser.close()
        except Exception as exc:
            logger.warning("playwright_scrape_failed", place_id=place_id, error=str(exc))

        return data

    def _parse_relative_days(self, text: str) -> int | None:
        """Parse '3 days ago', '2 weeks ago', '1 month ago' → integer days."""
        text = text.lower()
        m = re.search(r"(\d+)\s+(day|week|month|year)", text)
        if not m:
            return None
        n, unit = int(m.group(1)), m.group(2)
        if unit == "day":
            return n
        if unit == "week":
            return n * 7
        if unit == "month":
            return n * 30
        if unit == "year":
            return n * 365
        return None

    # ------------------------------------------------------------------
    # Citation check via SearXNG
    # ------------------------------------------------------------------

    def _check_citations(
        self,
        business_name: str,
        phone: str | None,
        address: str | None,
    ) -> dict[str, Any]:
        if not phone and not address:
            return {"consistent": 0, "total_checked": 0}

        query_parts = [f'"{business_name}"']
        if phone:
            query_parts.append(f'"{phone}"')
        site_filter = " OR ".join(f"site:{d}" for d in self._directories[:5])
        query = " ".join(query_parts) + " " + site_filter

        try:
            results = web_search(query, num_results=10)
        except Exception as exc:
            logger.warning("citation_search_failed", error=str(exc))
            return {"consistent": 0, "total_checked": 0}

        consistent = 0
        for r in results:
            content = r.get("content", "").lower()
            if business_name.lower() in content:
                if not phone or phone.replace("-", "").replace("(", "").replace(")", "").replace(" ", "") in content.replace("-", "").replace("(", "").replace(")", "").replace(" ", ""):
                    consistent += 1

        return {"consistent": consistent, "total_checked": len(results)}

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _calculate_scores(
        self,
        places: dict[str, Any],
        playwright: dict[str, Any],
        nap: dict[str, Any],
        keyword: str | None,
    ) -> tuple[dict[str, int], dict[str, Any]]:
        """Return (capped_scores, raw_detail) where capped_scores respects weights."""
        raw: dict[str, Any] = {}

        # -- Completeness (25) --
        comp = 0
        comp += 5 if places.get("name") else 0
        comp += 4 if places.get("formatted_address") else 0
        comp += 4 if places.get("formatted_phone_number") else 0
        comp += 4 if places.get("website") else 0
        comp += 4 if places.get("opening_hours") else 0
        comp += 4 if places.get("editorial_summary") else 0
        raw["completeness"] = comp

        # -- Photos (15) --
        photo_count = len(places.get("photos", []))
        if photo_count >= 16:
            photo_score = 15
        elif photo_count >= 6:
            photo_score = 10
        elif photo_count >= 1:
            photo_score = 5
        else:
            photo_score = 0
        raw["photos"] = {"count": photo_count, "score": photo_score}

        # -- Reviews (25) --
        count = places.get("user_ratings_total", 0) or 0
        rating = places.get("rating", 0.0) or 0.0
        if count >= 100:
            count_score = 15
        elif count >= 50:
            count_score = 10
        elif count >= 10:
            count_score = 5
        else:
            count_score = 0

        if rating >= 4.5:
            rating_score = 5
        elif rating >= 4.0:
            rating_score = 3
        elif rating >= 3.5:
            rating_score = 1
        else:
            rating_score = 0

        reviews = places.get("reviews", []) or []
        responses = sum(1 for r in reviews if r.get("owner_response"))
        response_rate = responses / len(reviews) if reviews else 0.0
        response_score = 5 if response_rate >= 0.8 else (3 if response_rate >= 0.4 else 0)

        review_score = count_score + rating_score + response_score
        raw["reviews"] = {
            "count": count,
            "rating": rating,
            "response_rate": round(response_rate, 2),
            "score": review_score,
        }

        # -- Posts (10) --
        days_ago = playwright.get("last_post_days_ago")
        if days_ago is None:
            post_score = 0
        elif days_ago <= 7:
            post_score = 10
        elif days_ago <= 30:
            post_score = 7
        elif days_ago <= 90:
            post_score = 4
        else:
            post_score = 0
        raw["posts"] = {"count": playwright.get("posts_count", 0), "last_post_days_ago": days_ago, "score": post_score}

        # -- Q&A (5) --
        qa_count = playwright.get("qa_count", 0)
        qa_answered = playwright.get("qa_answered", 0)
        if qa_count == 0:
            qa_score = 0
        elif qa_answered > 0:
            qa_score = 5
        else:
            qa_score = 2
        raw["qa"] = {"questions": qa_count, "answered": qa_answered, "score": qa_score}

        # -- Services (5) --
        services_score = 5 if playwright.get("services_listed") else 0
        raw["services"] = {"listed": playwright.get("services_listed", False), "score": services_score}

        # -- Keywords (10) --
        kw_score = 0
        if keyword:
            kw = keyword.lower()
            name = (places.get("name") or "").lower()
            desc = (places.get("editorial_summary", {}) or {}).get("overview", "").lower()
            types = " ".join(places.get("types") or []).lower()
            if kw in name:
                kw_score += 4
            if kw in desc:
                kw_score += 3
            if kw in types:
                kw_score += 3
        raw["keywords"] = {"keyword": keyword, "score": kw_score}

        # -- Citations (5) --
        consistent = nap.get("consistent", 0)
        if consistent >= 7:
            citation_score = 5
        elif consistent >= 4:
            citation_score = 3
        elif consistent >= 1:
            citation_score = 1
        else:
            citation_score = 0
        raw["citations"] = {"consistent": consistent, "total_checked": nap.get("total_checked", 0), "score": citation_score}

        scores = {
            "completeness": min(comp, self._weights.get("completeness", 25)),
            "photos": min(photo_score, self._weights.get("photos", 15)),
            "reviews": min(review_score, self._weights.get("reviews", 25)),
            "posts": min(post_score, self._weights.get("posts", 10)),
            "qa": min(qa_score, self._weights.get("qa", 5)),
            "services": min(services_score, self._weights.get("services", 5)),
            "keywords": min(kw_score, self._weights.get("keywords", 10)),
            "citations": min(citation_score, self._weights.get("citations", 5)),
        }
        return scores, raw

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def _build_recommendations(
        self,
        scores: dict[str, int],
        raw: dict[str, Any],
        places: dict[str, Any],
        playwright: dict[str, Any],
    ) -> list[dict[str, Any]]:
        recs: list[dict[str, Any]] = []

        if scores["completeness"] < 20:
            missing = []
            if not places.get("formatted_phone_number"):
                missing.append("phone number")
            if not places.get("website"):
                missing.append("website URL")
            if not places.get("editorial_summary"):
                missing.append("business description")
            if not places.get("opening_hours"):
                missing.append("business hours")
            if missing:
                recs.append({"category": "completeness", "priority": "HIGH",
                             "action": f"Add missing profile fields: {', '.join(missing)}"})

        if scores["photos"] < 10:
            recs.append({"category": "photos", "priority": "HIGH",
                         "action": f"Upload more photos (you have {raw['photos']['count']}, aim for 20+). Include interior, exterior, team, and product shots."})

        if scores["reviews"] < 20:
            review_data = raw.get("reviews", {})
            if review_data.get("count", 0) < 50:
                recs.append({"category": "reviews", "priority": "HIGH",
                             "action": "Implement a systematic review request process. Ask every satisfied customer to leave a review within 24 hours of service."})
            if (review_data.get("response_rate", 0)) < 0.5:
                recs.append({"category": "reviews", "priority": "MEDIUM",
                             "action": "Respond to all reviews (you're currently responding to fewer than 50%). Responding within 24 hours improves local ranking."})

        if scores["posts"] < 7:
            recs.append({"category": "posts", "priority": "MEDIUM",
                         "action": "Post a Google Business Profile update at least once per week. Share offers, photos, or events to show Google the business is active."})

        if scores["qa"] == 0:
            recs.append({"category": "qa", "priority": "LOW",
                         "action": "Seed your Q&A section with 5 common customer questions and answer them. This improves trust and indexable content."})

        if scores["services"] == 0:
            recs.append({"category": "services", "priority": "MEDIUM",
                         "action": "Add your services and products to your GBP. Businesses with services listed appear in more specific searches."})

        if scores["citations"] < 3:
            recs.append({"category": "citations", "priority": "HIGH",
                         "action": "Your business information (Name/Address/Phone) is inconsistent or missing from key directories. Submit to Yelp, YellowPages, BBB to improve local SEO authority."})

        # Sort by priority
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        recs.sort(key=lambda r: order.get(r["priority"], 3))
        return recs[:10]
