"""
Blog post writer — research → outline → draft → SEO optimize → publish.

Publish modes (per product config):
  wordpress  — WordPress REST API (app password auth)
  markdown   — commit .md file directly to repo path
"""

from __future__ import annotations

import re
import textwrap
from typing import Any

import httpx

from shared.llm.client import llm, web_search
from shared.logger import get_logger

from .db import ContentDB

logger = get_logger(__name__)

_VOICE_SYSTEM = """You are Dutch — a contractor who built software to solve his own problems.

Voice rules (always):
- First person, active voice. Short sentences. No corporate language.
- Every post contains one concrete, specific, actionable thing — not vague advice.
- Talk about the work, the problems, what actually fixes them.
- No exclamation marks. No buzzwords. No filler.
- Write like you'd explain it to another contractor over coffee.

SEO rules:
- Put the target keyword in the title (H1), the first 100 words, and the meta description.
- Meta description: 120-155 characters, plain sentence, includes keyword.
- Use H2 subheadings. No keyword stuffing.
- Aim for 2-3 internal links where relevant.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class BlogWriter:

    def __init__(self, db: ContentDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def write(
        self,
        product: str,
        topic: str,
        target_audience: str,
        word_count: int = 800,
        publish: bool = False,
    ) -> dict[str, Any]:
        # 1. Research
        search_results = self._research(topic, product)

        # 2. Get existing posts for internal linking
        existing = self._db.get_recent_pieces(product=product, platform="blog", limit=20)

        # 3. Draft
        draft = self._draft(topic, target_audience, word_count, search_results, existing)

        # 4. Extract title, meta, body
        title = self._extract_title(draft, topic)
        meta_description = self._generate_meta(title, topic, draft)
        body = self._inject_internal_links(draft, existing)
        links_added = body.count("](http") - draft.count("](http")
        links_added = max(links_added, 0)

        # 5. Save draft to DB
        piece_id = self._db.save_piece(
            product=product,
            platform="blog",
            content_type="blog_post",
            title=title,
            body=body,
            status="draft",
        )

        result: dict[str, Any] = {
            "piece_id": piece_id,
            "title": title,
            "meta_description": meta_description,
            "internal_links_added": links_added,
            "status": "draft",
            "word_count": len(body.split()),
        }

        # 6. Publish if requested
        if publish:
            pub = self._publish(product, title, body, meta_description, piece_id)
            result.update(pub)

        return result

    # ------------------------------------------------------------------

    def _research(self, topic: str, product: str) -> list[dict[str, str]]:
        queries = [
            f"{topic} guide tips",
            f"{topic} {product} best practices",
        ]
        results: list[dict[str, str]] = []
        for q in queries:
            try:
                results.extend(web_search(q, num_results=5))
            except Exception as exc:
                logger.warning("blog_research_failed", query=q, error=str(exc))
        return results[:10]

    def _draft(
        self,
        topic: str,
        target_audience: str,
        word_count: int,
        research: list[dict[str, str]],
        existing: list[dict[str, Any]],
    ) -> str:
        snippets = "\n\n".join(
            f"Source: {r['title']}\n{r['content']}"
            for r in research[:8]
            if r.get("content")
        )
        existing_titles = "\n".join(
            f"- {p['title']}: {p.get('url', '')}"
            for p in existing[:10]
        )

        prompt = (
            f"Topic: {topic}\n"
            f"Target audience: {target_audience}\n"
            f"Target word count: {word_count}\n\n"
            f"Research snippets:\n{snippets or 'No external data.'}\n\n"
            f"Existing posts for internal linking:\n{existing_titles or 'None.'}\n\n"
            "Write the full blog post in Markdown. Start with # Title (H1 containing the keyword). "
            "First paragraph must mention the keyword. Include H2 subheadings. "
            "Where natural, link to 2-3 existing posts using their full URLs."
        )

        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_VOICE_SYSTEM,
            max_tokens=2000,
            metadata={"caller": "content.blog_writer"},
        ).content[0].text.strip()

    def _extract_title(self, draft: str, fallback_topic: str) -> str:
        match = re.search(r"^#\s+(.+)$", draft, re.MULTILINE)
        if match:
            return match.group(1).strip()
        first_line = draft.split("\n")[0].strip().lstrip("#").strip()
        return first_line or fallback_topic

    def _generate_meta(self, title: str, keyword: str, body: str) -> str:
        # Use first non-heading paragraph as base, then truncate
        paragraphs = [
            line.strip()
            for line in body.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        base = paragraphs[0] if paragraphs else title
        # Ensure keyword present
        if keyword.lower() not in base.lower():
            base = f"{keyword.title()}: {base}"
        meta = textwrap.shorten(base, width=155, placeholder="...")
        return meta

    def _inject_internal_links(
        self, draft: str, existing: list[dict[str, Any]]
    ) -> str:
        """Add up to 2 internal links by replacing plain-text title references."""
        added = 0
        body = draft
        for piece in existing:
            if added >= 2:
                break
            title = piece.get("title", "")
            url = piece.get("url", "")
            if not title or not url:
                continue
            # Only link a keyword phrase if it appears unlinked
            first_word = title.split()[0] if title.split() else ""
            if first_word and first_word.lower() in body.lower() and url not in body:
                pattern = re.compile(re.escape(title), re.IGNORECASE)
                body, n = pattern.subn(f"[{title}]({url})", body, count=1)
                if n:
                    added += 1
        return body

    def _publish(
        self,
        product: str,
        title: str,
        body: str,
        meta: str,
        piece_id: str,
    ) -> dict[str, Any]:
        product_cfg = self._cfg.get("products", {}).get(product, {})
        mode = product_cfg.get("publish_mode", "markdown")

        if mode == "wordpress":
            return self._publish_wordpress(product_cfg, title, body, meta, piece_id)
        return self._publish_markdown(product_cfg, title, body, meta, piece_id)

    def _publish_wordpress(
        self,
        product_cfg: dict[str, Any],
        title: str,
        body: str,
        meta: str,
        piece_id: str,
    ) -> dict[str, Any]:
        wp_url = product_cfg["wordpress_url"].rstrip("/")
        auth = (product_cfg["wordpress_user"], product_cfg["wordpress_app_password"])

        resp = httpx.post(
            f"{wp_url}/wp-json/wp/v2/posts",
            auth=auth,
            json={
                "title": title,
                "content": body,
                "status": "publish",
                "meta": {"description": meta},
            },
            timeout=30,
        )

        if resp.status_code in (200, 201):
            data = resp.json()
            post_url = data.get("link", "")
            self._db.update_piece(piece_id, status="published", url=post_url)
            logger.info("blog_published_wordpress", piece_id=piece_id, url=post_url)
            return {"status": "published", "url": post_url, "wp_id": data.get("id")}

        logger.warning("blog_wordpress_publish_failed", status=resp.status_code)
        return {"status": "draft", "error": f"WordPress returned {resp.status_code}"}

    def _publish_markdown(
        self,
        product_cfg: dict[str, Any],
        title: str,
        body: str,
        meta: str,
        piece_id: str,
    ) -> dict[str, Any]:
        import os
        import subprocess

        repo_path = product_cfg.get("repo_path", ".")
        posts_dir = product_cfg.get("posts_dir", "content/blog")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
        filename = f"{slug}.md"
        full_dir = os.path.join(repo_path, posts_dir)
        os.makedirs(full_dir, exist_ok=True)
        filepath = os.path.join(full_dir, filename)

        frontmatter = (
            f"---\ntitle: \"{title}\"\ndescription: \"{meta}\"\n"
            f"piece_id: {piece_id}\n---\n\n"
        )
        with open(filepath, "w") as f:
            f.write(frontmatter + body)

        result = subprocess.run(
            ["git", "add", filepath, "&&", "git", "commit", "-m", f"content: {title}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

        self._db.update_piece(piece_id, status="published")
        logger.info("blog_published_markdown", piece_id=piece_id, file=filepath)
        return {
            "status": "published",
            "file": filepath,
            "commit_sha": result.stdout.strip()[:40] if result.returncode == 0 else None,
        }
