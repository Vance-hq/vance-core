"""
Multi-source lead scraper for Forge.

Sources (all open-source / free-tier):
  1. Google Maps   — Playwright (business name, phone, website, category)
  2. LinkedIn      — Playwright (people search by title + industry)
  3. Apollo.io     — free tier API (50 lookups/month, email enrichment)
  4. Hunter.io     — free tier API (25 lookups/month, email finder)
  5. SearXNG       — email pattern search ("[role] [company] [city] email")
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import quote_plus

import httpx

from shared.config.settings import settings
from shared.llm.client import web_search
from shared.logger import get_logger

logger = get_logger(__name__)

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", settings.PLAYWRIGHT_BROWSERS_PATH)


class LeadScraper:
    _UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def build_lead_list(
        self,
        persona: dict[str, Any],
        quantity: int,
        product: str,
    ) -> list[dict[str, Any]]:
        """Scrape + enrich leads matching persona. Returns enriched list."""
        title = persona.get("title", "")
        industry = persona.get("industry", "")
        city = persona.get("geography", "")
        company_size = persona.get("company_size", "")

        leads: list[dict[str, Any]] = []

        # Google Maps for local businesses
        if title or industry:
            query = f"{industry or title} {company_size}".strip()
            maps_leads = self.scrape_google_maps(query, city, limit=max(quantity, 50))
            leads.extend(maps_leads)
            logger.info("scraper_google_maps", count=len(maps_leads))

        # LinkedIn for people
        if title:
            li_leads = self.scrape_linkedin(title, industry, city, limit=max(quantity, 30))
            leads.extend(li_leads)
            logger.info("scraper_linkedin", count=len(li_leads))

        # Deduplicate by email
        seen_emails: set[str] = set()
        unique: list[dict[str, Any]] = []
        for lead in leads:
            email = (lead.get("email") or "").lower().strip()
            if email and email in seen_emails:
                continue
            if email:
                seen_emails.add(email)
            unique.append(lead)

        # Enrich with Apollo + Hunter until quantity is met
        enriched: list[dict[str, Any]] = []
        for lead in unique[:quantity]:
            lead["product"] = product
            lead = self._enrich(lead)
            if lead.get("email"):
                enriched.append(lead)

        logger.info("scraper_build_complete", total=len(enriched), product=product)
        return enriched

    # ------------------------------------------------------------------
    # Source: Google Maps (Playwright)
    # ------------------------------------------------------------------

    def scrape_google_maps(self, query: str, city: str, limit: int) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("playwright_not_installed")
            return []

        results: list[dict[str, Any]] = []
        search = f"{query} {city}".strip()
        url = f"https://www.google.com/maps/search/{quote_plus(search)}"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(user_agent=self._UA)
                page = ctx.new_page()
                page.goto(url, timeout=30_000)

                # Accept cookies if dialog appears
                try:
                    page.click('[aria-label="Accept all"]', timeout=3_000)
                except Exception:
                    pass

                try:
                    page.wait_for_selector('[role="feed"]', timeout=15_000)
                except Exception:
                    browser.close()
                    return []

                seen: set[str] = set()
                scroll_attempts = 0

                while len(results) < limit and scroll_attempts < 20:
                    items = page.query_selector_all('[role="article"]')
                    for item in items:
                        if len(results) >= limit:
                            break
                        try:
                            name_el = item.query_selector('[aria-label]')
                            name = (name_el.get_attribute("aria-label") or "").strip() if name_el else ""
                            if not name or name in seen:
                                continue
                            seen.add(name)

                            item.click()
                            page.wait_for_timeout(1_200)

                            detail = page.query_selector('[role="main"]')
                            phone = website = category = ""

                            if detail:
                                # Phone
                                ph_el = detail.query_selector('[data-tooltip="Copy phone number"]')
                                if ph_el:
                                    phone = ph_el.get_attribute("aria-label", "").replace("Phone:", "").strip()

                                # Website
                                web_el = detail.query_selector('a[data-value="Website"]')
                                if not web_el:
                                    web_el = detail.query_selector('a[href^="http"][aria-label*="website" i]')
                                if web_el:
                                    website = web_el.get_attribute("href", "")

                                # Category
                                cat_el = detail.query_selector('[jsaction*="category"]')
                                if not cat_el:
                                    cat_el = detail.query_selector('button[jsaction*="pane.rating.category"]')
                                if cat_el:
                                    category = cat_el.inner_text().strip()

                            results.append({
                                "company": name,
                                "phone": phone,
                                "website": website,
                                "category": category,
                                "city": city,
                                "source": "google_maps",
                            })
                        except Exception:
                            continue

                    # Scroll the feed to load more results
                    page.evaluate("document.querySelector('[role=\"feed\"]')?.scrollBy(0, 600)")
                    page.wait_for_timeout(800)
                    scroll_attempts += 1

                browser.close()
        except Exception as exc:
            logger.warning("google_maps_scrape_failed", error=str(exc))

        return results

    # ------------------------------------------------------------------
    # Source: LinkedIn (Playwright, cookie-based session)
    # ------------------------------------------------------------------

    def scrape_linkedin(self, title: str, industry: str, city: str, limit: int) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("playwright_not_installed")
            return []

        cookies_path = settings.FORGE_LINKEDIN_COOKIES_PATH
        if not os.path.exists(cookies_path):
            logger.warning("linkedin_cookies_missing", path=cookies_path)
            return []

        results: list[dict[str, Any]] = []
        search_url = (
            f"https://www.linkedin.com/search/results/people/"
            f"?keywords={quote_plus(title)}"
            f"&geoUrn={quote_plus(city)}"
        )

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(user_agent=self._UA)
                with open(cookies_path) as f:
                    ctx.add_cookies(json.load(f))
                page = ctx.new_page()
                page.goto(search_url, timeout=30_000)
                page.wait_for_timeout(2_000)

                page_num = 1
                while len(results) < limit and page_num <= 5:
                    try:
                        page.wait_for_selector('[data-view-name="search-entity-result-universal-template"]', timeout=10_000)
                    except Exception:
                        break

                    cards = page.query_selector_all('[data-view-name="search-entity-result-universal-template"]')
                    for card in cards:
                        if len(results) >= limit:
                            break
                        try:
                            name_el = card.query_selector('.entity-result__title-text a')
                            name = name_el.inner_text().strip() if name_el else ""
                            if not name:
                                continue

                            title_el = card.query_selector('.entity-result__primary-subtitle')
                            subtitle_el = card.query_selector('.entity-result__secondary-subtitle')

                            full_title = title_el.inner_text().strip() if title_el else ""
                            location = subtitle_el.inner_text().strip() if subtitle_el else ""

                            parts = name.split(" ", 1)
                            results.append({
                                "first_name": parts[0],
                                "last_name": parts[1] if len(parts) > 1 else "",
                                "title": full_title,
                                "city": location or city,
                                "source": "linkedin",
                            })
                        except Exception:
                            continue

                    # Next page
                    next_btn = page.query_selector('[aria-label="Next"]')
                    if next_btn and next_btn.is_enabled():
                        next_btn.click()
                        page.wait_for_timeout(2_000)
                        page_num += 1
                    else:
                        break

                browser.close()
        except Exception as exc:
            logger.warning("linkedin_scrape_failed", error=str(exc))

        return results

    # ------------------------------------------------------------------
    # Enrichment: Apollo.io free tier
    # ------------------------------------------------------------------

    def enrich_apollo(self, lead: dict[str, Any]) -> dict[str, Any]:
        if not settings.FORGE_APOLLO_API_KEY:
            return lead
        try:
            resp = httpx.post(
                "https://api.apollo.io/v1/people/match",
                json={
                    "api_key": settings.FORGE_APOLLO_API_KEY,
                    "first_name": lead.get("first_name", ""),
                    "last_name": lead.get("last_name", ""),
                    "organization_name": lead.get("company", ""),
                    "domain": _domain_from_website(lead.get("website", "")),
                },
                timeout=10,
            )
            if resp.status_code == 200:
                person = resp.json().get("person", {})
                if person.get("email"):
                    lead["email"] = person["email"]
                if person.get("title") and not lead.get("title"):
                    lead["title"] = person["title"]
                if person.get("phone_numbers"):
                    lead.setdefault("phone", person["phone_numbers"][0].get("raw_number", ""))
        except Exception as exc:
            logger.debug("apollo_enrich_failed", error=str(exc))
        return lead

    # ------------------------------------------------------------------
    # Enrichment: Hunter.io free tier
    # ------------------------------------------------------------------

    def enrich_hunter(self, lead: dict[str, Any]) -> dict[str, Any]:
        if not settings.FORGE_HUNTER_API_KEY or not lead.get("company"):
            return lead
        domain = _domain_from_website(lead.get("website", "")) or _guess_domain(lead.get("company", ""))
        if not domain:
            return lead
        try:
            resp = httpx.get(
                "https://api.hunter.io/v2/email-finder",
                params={
                    "domain": domain,
                    "first_name": lead.get("first_name", ""),
                    "last_name": lead.get("last_name", ""),
                    "api_key": settings.FORGE_HUNTER_API_KEY,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                if data.get("email") and not lead.get("email"):
                    lead["email"] = data["email"]
        except Exception as exc:
            logger.debug("hunter_enrich_failed", error=str(exc))
        return lead

    # ------------------------------------------------------------------
    # Enrichment: SearXNG email pattern search
    # ------------------------------------------------------------------

    def search_email_pattern(self, lead: dict[str, Any]) -> dict[str, Any]:
        if lead.get("email"):
            return lead
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        company = lead.get("company", "")
        city = lead.get("city", "")
        if not (name or company):
            return lead
        try:
            query = f'"{name}" "{company}" {city} email'
            results = web_search(query, num_results=5)
            for r in results:
                emails = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', r.get("content", ""))
                if emails:
                    lead["email"] = emails[0]
                    break
        except Exception as exc:
            logger.debug("searxng_email_search_failed", error=str(exc))
        return lead

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _enrich(self, lead: dict[str, Any]) -> dict[str, Any]:
        """Run all enrichment sources in order until email is found."""
        if not lead.get("email"):
            lead = self.enrich_apollo(lead)
        if not lead.get("email"):
            lead = self.enrich_hunter(lead)
        if not lead.get("email"):
            lead = self.search_email_pattern(lead)
        return lead


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _domain_from_website(website: str) -> str:
    if not website:
        return ""
    website = re.sub(r"^https?://", "", website)
    website = website.split("/")[0].lstrip("www.")
    return website


def _guess_domain(company: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "", company.lower())
    return f"{slug}.com" if slug else ""
