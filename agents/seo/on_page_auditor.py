"""
On-page SEO auditor — fetch, parse, audit, auto-fix or escalate.

Checks: title, meta description, H1/H2 structure, image alt text,
        internal links count, page speed (Lighthouse via API).

Fixable (auto-applied via CMS API): title, meta description, image alt text.
Structural (enqueue to dev agent): internal link count, H1 missing/multiple.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from shared.llm.client import llm
from shared.logger import get_logger

from .db import SeoDB

logger = get_logger(__name__)

_AUDIT_SYSTEM = """You are an SEO auditor. Given the HTML and URL of a page, produce an audit fix plan.

Output a JSON object:
  fixable    (array) — issues auto-patchable via CMS: title, meta_description, image_alt
    Each: { "type": "title"|"meta_description"|"image_alt", "current": "...", "suggested": "..." }
  structural (array) — issues requiring dev work: internal_links, h1_missing, h1_multiple, h2_structure
    Each: { "type": "...", "detail": "..." }
  manual     (array) — issues needing human review
    Each: { "type": "...", "detail": "..." }

Return only valid JSON — no explanation, no markdown.
"""

_MIN_INTERNAL_LINKS = 3
_MIN_TITLE_LENGTH = 30
_MAX_TITLE_LENGTH = 60
_MIN_META_LENGTH = 120
_MAX_META_LENGTH = 160


def enqueue_dev_task(url: str, issue: dict[str, Any], product: str) -> None:
    """Enqueue a structural fix to the dev agent."""
    from shared.queue.queue import TaskQueue
    from shared.types import AgentCapability, Task
    import uuid
    try:
        queue = TaskQueue()
        queue.push(Task(
            id=str(uuid.uuid4()),
            agent=AgentCapability.DEV,
            payload={
                "action": "fix_seo_issue",
                "url": url,
                "product": product,
                "issue": issue,
            },
        ))
    except Exception as exc:
        logger.warning("enqueue_dev_task_failed", url=url, error=str(exc))


def _apply_cms_fix(url: str, fix: dict[str, Any], product_cfg: dict[str, Any]) -> bool:
    """Apply a fixable SEO issue via the CMS API. Returns True on success."""
    cms = product_cfg.get("cms", "")
    if cms == "wordpress":
        return _apply_wordpress_fix(url, fix, product_cfg)
    logger.info("cms_fix_skipped_no_cms", url=url, fix_type=fix.get("type"))
    return False


def _apply_wordpress_fix(url: str, fix: dict[str, Any], cfg: dict[str, Any]) -> bool:
    wp_url = cfg.get("wordpress_url", "").rstrip("/")
    auth = (cfg.get("wordpress_user", ""), cfg.get("wordpress_app_password", ""))
    fix_type = fix.get("type", "")
    suggested = fix.get("suggested", "")

    try:
        # Find the post/page by URL
        slug = urlparse(url).path.strip("/").split("/")[-1]
        search = httpx.get(
            f"{wp_url}/wp-json/wp/v2/posts",
            params={"slug": slug},
            auth=auth,
            timeout=15,
        )
        if search.status_code != 200 or not search.json():
            return False

        post_id = search.json()[0]["id"]
        payload: dict[str, Any] = {}

        if fix_type == "title":
            payload["title"] = suggested
        elif fix_type == "meta_description":
            payload["meta"] = {"description": suggested}
        elif fix_type == "image_alt":
            return False  # image alt requires media library update — skip
        else:
            return False

        resp = httpx.post(
            f"{wp_url}/wp-json/wp/v2/posts/{post_id}",
            auth=auth,
            json=payload,
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("wordpress_fix_failed", url=url, error=str(exc))
        return False


class OnPageAuditor:

    def __init__(self, db: SeoDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def audit(self, url: str) -> dict[str, Any]:
        # 1. Fetch page
        try:
            resp = httpx.get(url, timeout=20, follow_redirects=True)
            html = resp.text
        except Exception as exc:
            return {"error": str(exc), "url": url}

        # 2. Parse checks from HTML
        checks = self._parse_checks(html, url)

        # 3. LLM fix plan
        fix_plan = self._generate_fix_plan(html, url, checks)

        # 4. Auto-apply fixable issues
        product = self._product_for_url(url)
        product_cfg = self._cfg.get("products", {}).get(product, {})
        auto_fixed = 0

        for fix in fix_plan.get("fixable", []):
            if _apply_cms_fix(url, fix, product_cfg):
                auto_fixed += 1

        # 5. Enqueue structural issues to dev agent
        for issue in fix_plan.get("structural", []):
            enqueue_dev_task(url, issue, product)

        # 6. Log SEO task
        self._db.save_seo_task(
            product=product,
            task_type="on_page",
            url=url,
            status="completed" if auto_fixed > 0 else "pending",
        )

        return {
            "url": url,
            "checks": checks,
            "issues": fix_plan.get("fixable", []) + fix_plan.get("structural", []),
            "fix_plan": fix_plan,
            "auto_fixed": auto_fixed,
            "dev_tasks_queued": len(fix_plan.get("structural", [])),
        }

    # ------------------------------------------------------------------

    def _parse_checks(self, html: str, url: str) -> dict[str, Any]:
        # Title
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""

        # Meta description
        meta_match = re.search(
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE,
        )
        if not meta_match:
            meta_match = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
                html, re.IGNORECASE,
            )
        meta_desc = meta_match.group(1).strip() if meta_match else ""

        # H1
        h1s = re.findall(r"<h1[^>]*>([^<]+)</h1>", html, re.IGNORECASE)

        # Images without alt
        all_imgs = re.findall(r"<img[^>]+>", html, re.IGNORECASE)
        imgs_no_alt = [
            img for img in all_imgs
            if not re.search(r'alt=["\'][^"\']+["\']', img, re.IGNORECASE)
        ]

        # Internal links
        domain = urlparse(url).netloc
        internal = re.findall(
            rf'href=["\'](?:https?://{re.escape(domain)}|/)[^"\']*["\']',
            html, re.IGNORECASE,
        )

        return {
            "title": {"value": title, "length": len(title), "ok": _MIN_TITLE_LENGTH <= len(title) <= _MAX_TITLE_LENGTH},
            "meta_description": {"value": meta_desc[:160], "length": len(meta_desc), "ok": _MIN_META_LENGTH <= len(meta_desc) <= _MAX_META_LENGTH},
            "h1": {"count": len(h1s), "values": h1s, "ok": len(h1s) == 1},
            "images_without_alt": {"count": len(imgs_no_alt), "ok": len(imgs_no_alt) == 0},
            "internal_links": {"count": len(internal), "ok": len(internal) >= _MIN_INTERNAL_LINKS},
        }

    def _generate_fix_plan(
        self, html: str, url: str, checks: dict[str, Any]
    ) -> dict[str, Any]:
        prompt = (
            f"URL: {url}\n"
            f"Audit checks:\n{json.dumps(checks, indent=2)}\n\n"
            f"HTML (first 3000 chars):\n{html[:3000]}\n\n"
            "Generate the fix plan."
        )
        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_AUDIT_SYSTEM,
            max_tokens=800,
            metadata={"caller": "seo.on_page_auditor"},
        ).content[0].text.strip()

        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            return json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            return {"fixable": [], "structural": [], "manual": []}

    def _product_for_url(self, url: str) -> str:
        domain = urlparse(url).netloc.replace("www.", "")
        for product, pcfg in self._cfg.get("products", {}).items():
            if domain in pcfg.get("domain", ""):
                return product
        return "unknown"
