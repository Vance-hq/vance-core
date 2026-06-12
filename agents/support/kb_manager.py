"""
KB manager — weekly update of knowledge base from resolved tickets.

Process:
  1. Pull last 50 resolved tickets for a product
  2. LLM identifies which Q&As should become KB articles
  3. Draft + save articles to DB
  4. Commit Markdown files to docs repo via git
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import SupportDB

logger = get_logger(__name__)

_KB_SYSTEM = """You are a technical writer for a SaaS product.

Given a list of resolved support tickets, identify questions that were answered well
and should become knowledge base articles. Output a JSON array of objects:
  title  (string) — clear, specific article title
  body   (string) — full article text, written as step-by-step guidance

Focus on HOW_TO tickets. Skip BUG reports and COMPLAINT tickets.
Return only valid JSON — no explanation.
"""

_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)


class KBManager:

    def __init__(self, db: SupportDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def update(self, product: str) -> dict[str, Any]:
        tickets = self._db.list_resolved_tickets(product=product, limit=50)
        if not tickets:
            return {"product": product, "articles_created": 0}

        ticket_summaries = "\n\n".join(
            f"[{t['classification']}] {t['subject']}\n{t['body'][:300]}"
            for t in tickets
        )

        raw = llm.complete(
            messages=[{"role": "user", "content": ticket_summaries}],
            system=_KB_SYSTEM,
            max_tokens=3000,
            metadata={"caller": "support.kb_manager"},
        ).content[0].text.strip()

        try:
            match = _JSON_RE.search(raw)
            articles = json.loads(match.group() if match else raw)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("kb_json_parse_failed", raw_preview=raw[:80])
            articles = []

        source_ids = [t["id"] for t in tickets]
        created = 0
        for article in articles:
            title = article.get("title", "").strip()
            body = article.get("body", "").strip()
            if not title or not body:
                continue
            self._db.save_kb_article(
                product=product,
                title=title,
                body=body,
                source_ticket_ids=source_ids,
            )
            self._commit_article(product=product, title=title, body=body)
            created += 1

        logger.info("kb_updated", product=product, articles_created=created)
        return {"product": product, "articles_created": created}

    def search(self, product: str, query: str) -> list[dict[str, Any]]:
        return self._db.search_kb(product=product, query=query)

    # ------------------------------------------------------------------

    def _commit_article(self, product: str, title: str, body: str) -> None:
        docs_path = Path(self._cfg.get("docs_repo_path", "/tmp/docs"))
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        article_dir = docs_path / product / "kb"
        article_dir.mkdir(parents=True, exist_ok=True)
        file_path = article_dir / f"{slug}.md"
        file_path.write_text(f"# {title}\n\n{body}\n")

        try:
            subprocess.run(
                ["git", "add", str(file_path)],
                cwd=str(docs_path),
                capture_output=True,
                check=False,
            )
            subprocess.run(
                ["git", "commit", "-m", f"docs(kb): add {title}"],
                cwd=str(docs_path),
                capture_output=True,
                check=False,
            )
        except Exception as exc:
            logger.warning("kb_git_commit_failed", title=title, error=str(exc))
