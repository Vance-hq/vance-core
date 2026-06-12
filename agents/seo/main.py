"""
SEO agent — Google Business Profile, keyword research, on-page audits,
schema markup, citation consistency, and weekly rank tracking.

Actions:
  gbp_optimize       — audit + update + post for a Google Business Profile
  keyword_research   — keyword clusters, quick wins (p11-20)
  on_page_audit      — audit + auto-fix fixable issues + enqueue structural
  schema_markup      — generate and commit JSON-LD for a page
  citation_audit     — NAP consistency across top citation directories
  rank_tracker       — weekly ranking snapshots + drop alerts
"""

from __future__ import annotations

from typing import Any

from agents._base import AgentConfig, BaseAgent
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .citation_auditor import CitationAuditor
from .db import SeoDB
from .gbp_optimizer import GBPOptimizer
from .keyword_researcher import KeywordResearcher
from .on_page_auditor import OnPageAuditor
from .rank_tracker import RankTracker
from .schema_generator import SchemaGenerator

logger = get_logger(__name__)


class SeoAgent(BaseAgent):

    def __init__(self, agent_name: str, config: AgentConfig) -> None:
        super().__init__(agent_name, config)
        cfg = config.custom
        self._db = SeoDB()
        self._gbp = GBPOptimizer(self._db, cfg)
        self._keywords = KeywordResearcher(self._db, cfg)
        self._on_page = OnPageAuditor(self._db, cfg)
        self._schema = SchemaGenerator(cfg)
        self._citations = CitationAuditor(self._db, cfg)
        self._tracker = RankTracker(self._db, cfg)

    # ------------------------------------------------------------------
    # BaseAgent contract
    # ------------------------------------------------------------------

    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        p = task.payload

        dispatch = {
            "gbp_optimize":      lambda: self._handle_gbp(p),
            "keyword_research":  lambda: self._handle_keywords(p),
            "on_page_audit":     lambda: self._handle_on_page(p),
            "schema_markup":     lambda: self._handle_schema(p),
            "citation_audit":    lambda: self._handle_citations(p),
            "rank_tracker":      lambda: self._handle_rank_tracker(p),
        }

        handler = dispatch.get(action)
        if not handler:
            return TaskResult(
                task_id=task.id,
                success=False,
                output={"error": f"Unknown SEO action: {action}"},
            )

        logger.info("seo_task_started", action=action, task_id=task.id)
        output = handler()
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            self._db.get_last_gbp_audit(business="trusted_plumbing")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # gbp_optimize
    # ------------------------------------------------------------------

    def _handle_gbp(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          business        (str) — trusted_plumbing | localoutrank_demo
          gbp_location_id (str) — e.g. "locations/123456"
        """
        business = p.get("business", "")
        location_id = p.get("gbp_location_id", "")
        if not business or not location_id:
            return {"error": "business and gbp_location_id required"}
        return self._gbp.optimize(business=business, gbp_location_id=location_id)

    # ------------------------------------------------------------------
    # keyword_research
    # ------------------------------------------------------------------

    def _handle_keywords(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product    (str)
          seed_topic (str)
        """
        product = p.get("product", "")
        seed = p.get("seed_topic", "")
        if not product or not seed:
            return {"error": "product and seed_topic required"}
        return self._keywords.research(product=product, seed_topic=seed)

    # ------------------------------------------------------------------
    # on_page_audit
    # ------------------------------------------------------------------

    def _handle_on_page(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          url (str)
        """
        url = p.get("url", "")
        if not url:
            return {"error": "url required"}
        return self._on_page.audit(url=url)

    # ------------------------------------------------------------------
    # schema_markup
    # ------------------------------------------------------------------

    def _handle_schema(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          schema_type (str) — LocalBusiness | Service | FAQ | Review | HowTo
          product     (str)
          page_url    (str)

        Optional:
          faqs         (list) — for FAQ schema: [{"question": ..., "answer": ...}]
          page_title   (str)  — for HowTo/Service/Review
          page_content (str)  — for HowTo
          commit       (bool) — commit to repo
        """
        schema_type = p.get("schema_type", "")
        product = p.get("product", "")
        page_url = p.get("page_url", "")
        if not schema_type or not product or not page_url:
            return {"error": "schema_type, product, and page_url required"}

        return self._schema.generate(
            schema_type=schema_type,
            product=product,
            page_url=page_url,
            commit=bool(p.get("commit", False)),
            faqs=p.get("faqs"),
            page_title=p.get("page_title", ""),
            page_content=p.get("page_content", ""),
        )

    # ------------------------------------------------------------------
    # citation_audit
    # ------------------------------------------------------------------

    def _handle_citations(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          business (str) — trusted_plumbing | localoutrank_demo
        """
        business = p.get("business", "")
        if not business:
            return {"error": "business required"}
        return self._citations.audit(business=business)

    # ------------------------------------------------------------------
    # rank_tracker
    # ------------------------------------------------------------------

    def _handle_rank_tracker(self, p: dict[str, Any]) -> dict[str, Any]:
        """
        Required:
          product  (str)
          keywords (list[str])
        """
        product = p.get("product", "")
        keywords = p.get("keywords", [])
        if not product or not keywords:
            return {"error": "product and keywords required"}
        return self._tracker.track(product=product, keywords=keywords)


if __name__ == "__main__":
    config = AgentConfig.load("seo")
    SeoAgent("seo", config).run()
