"""Competitor activity watcher — pricing diff, blog posts, LinkedIn, jobs, G2/Capterra."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)

_ACTIVITY_THRESHOLD = 7  # LLM relevance score to trigger reporting dispatch


def _fetch_page_content(url: str) -> str:
    """Fetch page HTML. Playwright used when available; falls back to httpx."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=20_000, wait_until="domcontentloaded")
            content = page.content()
            browser.close()
            return content
    except Exception:
        import httpx

        resp = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        return resp.text


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:20]


def _serp_search(query: str, api_key: str, tbm: str = "", num: int = 5) -> list[dict[str, Any]]:
    """Call SerpAPI and return organic results."""
    import httpx

    params: dict[str, Any] = {"q": query, "api_key": api_key, "num": num}
    if tbm:
        params["tbm"] = tbm
    try:
        resp = httpx.get("https://serpapi.com/search", params=params, timeout=15)
        data = resp.json()
        return data.get("organic_results", data.get("news_results", []))
    except Exception as exc:
        logger.warning("serp_search_failed", query=query, error=str(exc))
        return []


class CompetitorWatcher:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        products_cfg = self._cfg.get("products", {})
        prod_cfg = products_cfg.get(product, {})
        competitors = prod_cfg.get("competitors", [])
        competitor_urls = prod_cfg.get("competitor_urls", {})
        api_key = self._cfg.get("serp_api_key", "")

        total_changes = 0
        items: list[dict[str, Any]] = []

        for competitor in competitors:
            urls = competitor_urls.get(competitor, {})

            # 1. Pricing page screenshot/content diff
            pricing_url = urls.get("pricing", "")
            if pricing_url:
                change = self._check_page_change(competitor, "pricing", pricing_url, product)
                if change:
                    items.append(change)
                    total_changes += 1

            # 2. New blog posts
            blog_domain = urls.get("blog", "")
            if blog_domain:
                posts = self._check_blog(competitor, blog_domain, api_key, product)
                items.extend(posts)
                total_changes += len(posts)

            # 3. LinkedIn founder posts (SerpAPI)
            linkedin_posts = self._check_linkedin(competitor, api_key, product)
            items.extend(linkedin_posts)
            total_changes += len(linkedin_posts)

            # 4. Job listings (signal of product direction)
            jobs = self._check_jobs(competitor, api_key, product)
            items.extend(jobs)
            total_changes += len(jobs)

            # 5. G2 / Capterra review trends
            reviews = self._check_reviews(competitor, api_key, product)
            items.extend(reviews)
            total_changes += len(reviews)

        if items:
            self._dispatch_to_reporting(product, items)

        return {
            "product": product,
            "competitors_checked": len(competitors),
            "changes_detected": total_changes,
            "items": items,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_page_change(
        self, competitor: str, page_type: str, url: str, product: str
    ) -> dict[str, Any] | None:
        try:
            content = _fetch_page_content(url)
        except Exception as exc:
            logger.warning("page_fetch_failed", competitor=competitor, url=url, error=str(exc))
            return None

        new_hash = _hash_content(content)
        old_hash = self._db.get_page_hash(competitor, page_type)
        self._db.upsert_page_hash(competitor, page_type, url, new_hash)

        if old_hash is None or old_hash == new_hash:
            return None

        summary = f"{competitor} {page_type.replace('_', ' ')} page changed"
        activity_id = self._db.save_competitor_activity(
            competitor=competitor,
            activity_type="screenshot_diff" if page_type == "pricing" else f"{page_type}_change",
            summary=summary,
            source_url=url,
            product=product,
            content_hash=new_hash,
        )
        return {"id": activity_id, "competitor": competitor, "type": page_type, "summary": summary, "url": url}

    def _check_blog(
        self, competitor: str, blog_domain: str, api_key: str, product: str
    ) -> list[dict[str, Any]]:
        if not api_key:
            return []
        results = _serp_search(f"site:{blog_domain} -site:reddit.com", api_key, num=3)
        items = []
        for r in results[:2]:  # limit to 2 newest
            title = r.get("title", "")
            link = r.get("link", "")
            if not title:
                continue
            activity_id = self._db.save_competitor_activity(
                competitor=competitor,
                activity_type="blog_post",
                summary=f"New blog post: {title}",
                source_url=link,
                product=product,
            )
            items.append({"id": activity_id, "competitor": competitor, "type": "blog_post", "summary": title, "url": link})
        return items

    def _check_linkedin(self, competitor: str, api_key: str, product: str) -> list[dict[str, Any]]:
        if not api_key:
            return []
        results = _serp_search(f"site:linkedin.com/posts {competitor} founder", api_key, num=3)
        items = []
        for r in results[:1]:
            title = r.get("title", "")
            link = r.get("link", "")
            if not title:
                continue
            activity_id = self._db.save_competitor_activity(
                competitor=competitor,
                activity_type="linkedin_post",
                summary=f"LinkedIn activity: {title}",
                source_url=link,
                product=product,
            )
            items.append({"id": activity_id, "competitor": competitor, "type": "linkedin_post", "summary": title, "url": link})
        return items

    def _check_jobs(self, competitor: str, api_key: str, product: str) -> list[dict[str, Any]]:
        if not api_key:
            return []
        results = _serp_search(f"{competitor} jobs hiring site:linkedin.com OR site:indeed.com", api_key, num=3)
        items = []
        for r in results[:1]:
            title = r.get("title", "")
            link = r.get("link", "")
            if not title:
                continue
            activity_id = self._db.save_competitor_activity(
                competitor=competitor,
                activity_type="job_listing",
                summary=f"Job listing: {title}",
                source_url=link,
                product=product,
            )
            items.append({"id": activity_id, "competitor": competitor, "type": "job_listing", "summary": title, "url": link})
        return items

    def _check_reviews(self, competitor: str, api_key: str, product: str) -> list[dict[str, Any]]:
        if not api_key:
            return []
        results = _serp_search(f"{competitor} reviews site:g2.com OR site:capterra.com", api_key, num=3)
        items = []
        for r in results[:1]:
            snippet = r.get("snippet", "")
            link = r.get("link", "")
            if not snippet:
                continue
            activity_id = self._db.save_competitor_activity(
                competitor=competitor,
                activity_type="review_trend",
                summary=f"Review activity: {snippet[:120]}",
                source_url=link,
                product=product,
            )
            items.append({"id": activity_id, "competitor": competitor, "type": "review_trend", "summary": snippet[:120], "url": link})
        return items

    def _dispatch_to_reporting(self, product: str, items: list[dict[str, Any]]) -> None:
        try:
            TaskQueue().push(
                "reporting",
                {
                    "action": "add_to_brief",
                    "section": "competitor_activity",
                    "product": product,
                    "data": {"changes": items},
                },
            )
        except Exception as exc:
            logger.warning("competitor_watcher_dispatch_failed", error=str(exc))
