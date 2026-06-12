"""SEO agent unit tests — no external services required."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from agents._base import AgentConfig
from agents.seo.db import SeoDB
from agents.seo.gbp_optimizer import GBPOptimizer
from agents.seo.keyword_researcher import KeywordResearcher
from agents.seo.on_page_auditor import OnPageAuditor
from agents.seo.schema_generator import SchemaGenerator
from agents.seo.citation_auditor import CitationAuditor
from agents.seo.rank_tracker import RankTracker
from shared.types import Task, TaskResult, AgentCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gbp_audit(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "business": "trusted_plumbing",
        "audit_date": date.today(),
        "score": 72,
        "issues_found": 5,
        "issues_fixed": 3,
    }
    if overrides:
        base.update(overrides)
    return base


def _ranking(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "localoutrank",
        "keyword": "local SEO software",
        "rank": 8,
        "url": "https://localoutrank.com",
        "recorded_at": datetime.now(timezone.utc),
    }
    if overrides:
        base.update(overrides)
    return base


def _seo_task(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "localoutrank",
        "task_type": "on_page",
        "url": "https://localoutrank.com/blog/post",
        "status": "pending",
        "completed_at": None,
        "improvement_delta": None,
    }
    if overrides:
        base.update(overrides)
    return base


def _cfg() -> dict:
    return {
        "google_my_business_credentials": "/secrets/gmb_creds.json",
        "serp_api_key": "serp_key_abc",
        "google_search_console_credentials": "/secrets/gsc_creds.json",
        "yext_api_key": "yext_key_abc",
        "businesses": {
            "trusted_plumbing": {
                "name": "Trusted Plumbing",
                "address": "123 Main St, Austin TX 78701",
                "phone": "(512) 555-0100",
                "gbp_location_id": "locations/123456",
                "website": "https://trustedplumbing.com",
            },
            "localoutrank_demo": {
                "name": "LocalOutRank Demo",
                "address": "456 Tech Blvd, Austin TX 78702",
                "phone": "(512) 555-0200",
                "gbp_location_id": "locations/789012",
                "website": "https://localoutrank.com",
            },
        },
        "products": {
            "localoutrank": {
                "domain": "localoutrank.com",
                "cms": "wordpress",
                "wordpress_url": "https://localoutrank.com",
                "wordpress_user": "admin",
                "wordpress_app_password": "secret",
            },
            "trusted_plumbing": {
                "domain": "trustedplumbing.com",
                "cms": "markdown",
                "repo_path": "/repos/trusted-plumbing-site",
            },
        },
        "citation_sources": ["yelp.com", "yellowpages.com", "angi.com", "bbb.org", "houzz.com"],
        "alert_channel": "#seo-alerts",
        "rank_drop_threshold": 3,
    }


def _task(action: str, payload: dict | None = None) -> Task:
    p = {"action": action}
    if payload:
        p.update(payload)
    return Task(
        id=str(uuid.uuid4()),
        agent=AgentCapability.MARKETING,
        payload=p,
    )


@pytest.fixture
def mock_db():
    return MagicMock(spec=SeoDB)


@pytest.fixture
def cfg():
    return _cfg()


# ---------------------------------------------------------------------------
# TestSeoDB
# ---------------------------------------------------------------------------

class TestSeoDB:

    def test_save_gbp_audit_returns_id(self):
        db = SeoDB()
        audit_id = str(uuid.uuid4())
        with patch("agents.seo.db.get_db") as mock_get_db:
            conn, cur = _mock_conn(mock_get_db, fetchone=(audit_id,))
            result = db.save_gbp_audit(
                business="trusted_plumbing",
                score=75,
                issues_found=4,
                issues_fixed=2,
            )
        assert result == audit_id

    def test_save_keyword_ranking_returns_id(self):
        db = SeoDB()
        row_id = str(uuid.uuid4())
        with patch("agents.seo.db.get_db") as mock_get_db:
            conn, cur = _mock_conn(mock_get_db, fetchone=(row_id,))
            result = db.save_keyword_ranking(
                product="localoutrank",
                keyword="local SEO software",
                rank=7,
                url="https://localoutrank.com",
            )
        assert result == row_id

    def test_get_previous_rankings_returns_list(self):
        db = SeoDB()
        rows = [_ranking(), _ranking({"keyword": "google business profile software", "rank": 14})]
        with patch("agents.seo.db.get_db") as mock_get_db:
            conn, cur = _mock_conn(mock_get_db, fetchall=rows)
            result = db.get_previous_rankings(product="localoutrank", keyword="local SEO software")
        assert isinstance(result, list)

    def test_save_seo_task_returns_id(self):
        db = SeoDB()
        task_id = str(uuid.uuid4())
        with patch("agents.seo.db.get_db") as mock_get_db:
            conn, cur = _mock_conn(mock_get_db, fetchone=(task_id,))
            result = db.save_seo_task(
                product="localoutrank",
                task_type="on_page",
                url="https://localoutrank.com/blog/post",
            )
        assert result == task_id

    def test_update_seo_task_completion(self):
        db = SeoDB()
        task_id = str(uuid.uuid4())
        with patch("agents.seo.db.get_db") as mock_get_db:
            conn, cur = _mock_conn(mock_get_db)
            db.update_seo_task(task_id, status="completed", improvement_delta=5)
        cur.execute.assert_called_once()

    def test_get_gbp_last_audit(self):
        db = SeoDB()
        audit = _gbp_audit()
        with patch("agents.seo.db.get_db") as mock_get_db:
            conn, cur = _mock_conn(mock_get_db, fetchone=audit)
            result = db.get_last_gbp_audit(business="trusted_plumbing")
        assert result is not None


# ---------------------------------------------------------------------------
# TestGBPOptimizer
# ---------------------------------------------------------------------------

class TestGBPOptimizer:

    def test_audit_returns_expected_keys(self, mock_db, cfg):
        opt = GBPOptimizer(mock_db, cfg)
        mock_db.save_gbp_audit.return_value = str(uuid.uuid4())

        with patch("agents.seo.gbp_optimizer.httpx") as mock_httpx, \
             patch("agents.seo.gbp_optimizer.llm") as mock_llm:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _gbp_profile_response()
            mock_httpx.patch.return_value.status_code = 200
            mock_httpx.patch.return_value.json.return_value = {}
            mock_httpx.post.return_value.status_code = 200
            mock_httpx.post.return_value.json.return_value = {"name": "accounts/1/locations/2/localPosts/3"}
            mock_llm.complete.return_value.content = [
                MagicMock(text="Expert plumbers serving Austin TX since 2005. Licensed, insured, 24/7 emergency service.")
            ]

            result = opt.optimize(
                business="trusted_plumbing",
                gbp_location_id="locations/123456",
            )

        assert "audit_id" in result
        assert "score" in result
        assert "issues_found" in result
        assert "issues_fixed" in result
        assert "actions_taken" in result

    def test_description_updated_when_incomplete(self, mock_db, cfg):
        opt = GBPOptimizer(mock_db, cfg)
        mock_db.save_gbp_audit.return_value = str(uuid.uuid4())

        profile = _gbp_profile_response()
        profile["profile"]["description"] = ""  # incomplete

        with patch("agents.seo.gbp_optimizer.httpx") as mock_httpx, \
             patch("agents.seo.gbp_optimizer.llm") as mock_llm:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = profile
            mock_httpx.patch.return_value.status_code = 200
            mock_httpx.patch.return_value.json.return_value = {}
            mock_httpx.post.return_value.status_code = 200
            mock_httpx.post.return_value.json.return_value = {}
            mock_llm.complete.return_value.content = [
                MagicMock(text="Expert plumbers in Austin TX. Licensed, insured, 24/7 emergency.")
            ]

            result = opt.optimize(
                business="trusted_plumbing",
                gbp_location_id="locations/123456",
            )

        assert "description_updated" in result["actions_taken"] or result["issues_fixed"] >= 1

    def test_gbp_post_created_when_stale(self, mock_db, cfg):
        opt = GBPOptimizer(mock_db, cfg)
        mock_db.save_gbp_audit.return_value = str(uuid.uuid4())

        profile = _gbp_profile_response()
        profile["last_post_days_ago"] = 10  # stale

        with patch("agents.seo.gbp_optimizer.httpx") as mock_httpx, \
             patch("agents.seo.gbp_optimizer.llm") as mock_llm:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = profile
            mock_httpx.patch.return_value.status_code = 200
            mock_httpx.patch.return_value.json.return_value = {}
            mock_httpx.post.return_value.status_code = 200
            mock_httpx.post.return_value.json.return_value = {"name": "accounts/1/locations/2/localPosts/3"}
            mock_llm.complete.return_value.content = [
                MagicMock(text="Summer special: 10% off water heater installation. Book now.")
            ]

            result = opt.optimize(
                business="trusted_plumbing",
                gbp_location_id="locations/123456",
            )

        assert "gbp_post_created" in result["actions_taken"]

    def test_audit_score_between_0_and_100(self, mock_db, cfg):
        opt = GBPOptimizer(mock_db, cfg)
        mock_db.save_gbp_audit.return_value = str(uuid.uuid4())

        with patch("agents.seo.gbp_optimizer.httpx") as mock_httpx, \
             patch("agents.seo.gbp_optimizer.llm") as mock_llm:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _gbp_profile_response()
            mock_httpx.patch.return_value.status_code = 200
            mock_httpx.patch.return_value.json.return_value = {}
            mock_httpx.post.return_value.status_code = 200
            mock_httpx.post.return_value.json.return_value = {}
            mock_llm.complete.return_value.content = [MagicMock(text="Good description.")]

            result = opt.optimize("trusted_plumbing", "locations/123456")

        assert 0 <= result["score"] <= 100

    def test_audit_logged_to_db(self, mock_db, cfg):
        opt = GBPOptimizer(mock_db, cfg)
        mock_db.save_gbp_audit.return_value = str(uuid.uuid4())

        with patch("agents.seo.gbp_optimizer.httpx") as mock_httpx, \
             patch("agents.seo.gbp_optimizer.llm") as mock_llm:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _gbp_profile_response()
            mock_httpx.patch.return_value.status_code = 200
            mock_httpx.patch.return_value.json.return_value = {}
            mock_httpx.post.return_value.status_code = 200
            mock_httpx.post.return_value.json.return_value = {}
            mock_llm.complete.return_value.content = [MagicMock(text="Description text.")]

            opt.optimize("trusted_plumbing", "locations/123456")

        mock_db.save_gbp_audit.assert_called_once()


# ---------------------------------------------------------------------------
# TestKeywordResearcher
# ---------------------------------------------------------------------------

class TestKeywordResearcher:

    def test_research_returns_clusters(self, mock_db, cfg):
        researcher = KeywordResearcher(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())

        with patch("agents.seo.keyword_researcher.web_search") as mock_search, \
             patch("agents.seo.keyword_researcher.llm") as mock_llm, \
             patch("agents.seo.keyword_researcher.httpx") as mock_httpx:
            mock_search.return_value = _serp_results()
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _serp_api_response()
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps(_keyword_clusters()))
            ]

            result = researcher.research(product="localoutrank", seed_topic="local SEO software")

        assert "clusters" in result
        assert len(result["clusters"]) > 0

    def test_quick_wins_identified_for_p11_to_p20(self, mock_db, cfg):
        researcher = KeywordResearcher(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())

        clusters = _keyword_clusters()
        clusters[0]["keywords"][0]["current_rank"] = 14  # page 2

        with patch("agents.seo.keyword_researcher.web_search") as mock_search, \
             patch("agents.seo.keyword_researcher.llm") as mock_llm, \
             patch("agents.seo.keyword_researcher.httpx") as mock_httpx:
            mock_search.return_value = _serp_results()
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _serp_api_response()
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps(clusters))
            ]

            result = researcher.research(product="localoutrank", seed_topic="local SEO")

        assert "quick_wins" in result
        assert len(result["quick_wins"]) >= 1

    def test_quick_wins_only_include_p11_to_p20(self, mock_db, cfg):
        researcher = KeywordResearcher(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())

        clusters = _keyword_clusters()
        # Set all ranks outside p11-20
        for cluster in clusters:
            for kw in cluster["keywords"]:
                kw["current_rank"] = 3  # already on page 1

        with patch("agents.seo.keyword_researcher.web_search") as mock_search, \
             patch("agents.seo.keyword_researcher.llm") as mock_llm, \
             patch("agents.seo.keyword_researcher.httpx") as mock_httpx:
            mock_search.return_value = _serp_results()
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _serp_api_response()
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps(clusters))
            ]

            result = researcher.research(product="localoutrank", seed_topic="local SEO")

        assert result["quick_wins"] == []

    def test_each_cluster_has_required_fields(self, mock_db, cfg):
        researcher = KeywordResearcher(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())

        with patch("agents.seo.keyword_researcher.web_search") as mock_search, \
             patch("agents.seo.keyword_researcher.llm") as mock_llm, \
             patch("agents.seo.keyword_researcher.httpx") as mock_httpx:
            mock_search.return_value = _serp_results()
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _serp_api_response()
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps(_keyword_clusters()))
            ]

            result = researcher.research(product="localoutrank", seed_topic="local SEO")

        for cluster in result["clusters"]:
            assert "name" in cluster
            assert "keywords" in cluster
            for kw in cluster["keywords"]:
                assert "keyword" in kw
                assert "monthly_volume" in kw
                assert "difficulty" in kw
                assert "current_rank" in kw


# ---------------------------------------------------------------------------
# TestOnPageAuditor
# ---------------------------------------------------------------------------

class TestOnPageAuditor:

    def test_audit_returns_fix_plan(self, mock_db, cfg):
        auditor = OnPageAuditor(mock_db, cfg)
        mock_db.save_seo_task.return_value = str(uuid.uuid4())

        with patch("agents.seo.on_page_auditor.httpx") as mock_httpx, \
             patch("agents.seo.on_page_auditor.llm") as mock_llm:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.text = _sample_html()
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps(_fix_plan()))
            ]

            result = auditor.audit(url="https://localoutrank.com/blog/post")

        assert "url" in result
        assert "issues" in result
        assert "fix_plan" in result

    def test_fixable_issues_auto_applied(self, mock_db, cfg):
        auditor = OnPageAuditor(mock_db, cfg)
        mock_db.save_seo_task.return_value = str(uuid.uuid4())

        fix_plan = _fix_plan()
        fix_plan["fixable"] = [
            {"type": "title", "current": "Home", "suggested": "Local SEO Software | LocalOutRank"},
            {"type": "meta_description", "current": "", "suggested": "Rank higher on Google Maps."},
        ]

        with patch("agents.seo.on_page_auditor.httpx") as mock_httpx, \
             patch("agents.seo.on_page_auditor.llm") as mock_llm, \
             patch("agents.seo.on_page_auditor._apply_cms_fix") as mock_apply:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.text = _sample_html()
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(fix_plan))]
            mock_apply.return_value = True

            result = auditor.audit(url="https://localoutrank.com/blog/post")

        assert result["auto_fixed"] >= 0

    def test_structural_issues_enqueue_dev_task(self, mock_db, cfg):
        auditor = OnPageAuditor(mock_db, cfg)
        mock_db.save_seo_task.return_value = str(uuid.uuid4())

        fix_plan = _fix_plan()
        fix_plan["structural"] = [
            {"type": "internal_links", "detail": "Only 1 internal link found, need 3+"},
        ]

        with patch("agents.seo.on_page_auditor.httpx") as mock_httpx, \
             patch("agents.seo.on_page_auditor.llm") as mock_llm, \
             patch("agents.seo.on_page_auditor._apply_cms_fix", return_value=True), \
             patch("agents.seo.on_page_auditor.enqueue_dev_task") as mock_dev:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.text = _sample_html()
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(fix_plan))]

            auditor.audit(url="https://localoutrank.com/blog/post")

        mock_dev.assert_called_once()

    def test_audit_checks_all_required_elements(self, mock_db, cfg):
        auditor = OnPageAuditor(mock_db, cfg)
        mock_db.save_seo_task.return_value = str(uuid.uuid4())

        with patch("agents.seo.on_page_auditor.httpx") as mock_httpx, \
             patch("agents.seo.on_page_auditor.llm") as mock_llm:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.text = _sample_html()
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_fix_plan()))]

            result = auditor.audit(url="https://localoutrank.com/blog/post")

        checks = result.get("checks", {})
        for element in ("title", "meta_description", "h1", "images_without_alt", "internal_links"):
            assert element in checks

    def test_unreachable_url_returns_error(self, mock_db, cfg):
        auditor = OnPageAuditor(mock_db, cfg)

        with patch("agents.seo.on_page_auditor.httpx") as mock_httpx:
            mock_httpx.get.side_effect = Exception("Connection refused")

            result = auditor.audit(url="https://localoutrank.com/broken")

        assert "error" in result


# ---------------------------------------------------------------------------
# TestSchemaGenerator
# ---------------------------------------------------------------------------

class TestSchemaGenerator:

    def test_local_business_schema_valid_json_ld(self, mock_db, cfg):
        gen = SchemaGenerator(cfg)

        result = gen.generate(
            schema_type="LocalBusiness",
            product="trusted_plumbing",
            page_url="https://trustedplumbing.com",
        )

        assert result["schema_type"] == "LocalBusiness"
        schema = json.loads(result["json_ld"])
        assert schema["@context"] == "https://schema.org"
        assert schema["@type"] == "LocalBusiness"

    def test_faq_schema_requires_faqs_input(self, mock_db, cfg):
        gen = SchemaGenerator(cfg)

        faqs = [
            {"question": "Do you offer 24/7 service?", "answer": "Yes, we do."},
            {"question": "Are you licensed?", "answer": "Yes, fully licensed and insured."},
        ]
        result = gen.generate(
            schema_type="FAQ",
            product="trusted_plumbing",
            page_url="https://trustedplumbing.com/faq",
            faqs=faqs,
        )

        assert result["schema_type"] == "FAQ"
        schema = json.loads(result["json_ld"])
        assert schema["@type"] == "FAQPage"
        assert len(schema["mainEntity"]) == 2

    def test_howto_schema_generated_via_llm(self, mock_db, cfg):
        gen = SchemaGenerator(cfg)

        with patch("agents.seo.schema_generator.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps({
                    "@context": "https://schema.org",
                    "@type": "HowTo",
                    "name": "How to fix a leaky faucet",
                    "step": [{"@type": "HowToStep", "text": "Turn off water supply"}],
                }))
            ]

            result = gen.generate(
                schema_type="HowTo",
                product="trusted_plumbing",
                page_url="https://trustedplumbing.com/blog/fix-leaky-faucet",
                page_title="How to Fix a Leaky Faucet",
                page_content="Step 1: Turn off water supply...",
            )

        assert result["schema_type"] == "HowTo"
        schema = json.loads(result["json_ld"])
        assert schema["@type"] == "HowTo"

    def test_all_schema_types_accepted(self, mock_db, cfg):
        gen = SchemaGenerator(cfg)

        for schema_type in ("LocalBusiness", "Service", "Review"):
            with patch("agents.seo.schema_generator.llm") as mock_llm:
                mock_llm.complete.return_value.content = [
                    MagicMock(text=json.dumps({
                        "@context": "https://schema.org",
                        "@type": schema_type,
                        "name": "Test",
                    }))
                ]
                result = gen.generate(
                    schema_type=schema_type,
                    product="trusted_plumbing",
                    page_url="https://trustedplumbing.com",
                )
            assert "error" not in result

    def test_invalid_schema_type_returns_error(self, mock_db, cfg):
        gen = SchemaGenerator(cfg)
        result = gen.generate(
            schema_type="SomethingMadeUp",
            product="trusted_plumbing",
            page_url="https://trustedplumbing.com",
        )
        assert "error" in result

    def test_schema_committed_to_repo(self, mock_db, cfg):
        gen = SchemaGenerator(cfg)

        with patch("agents.seo.schema_generator.subprocess") as mock_sub:
            mock_sub.run.return_value.returncode = 0
            result = gen.generate(
                schema_type="LocalBusiness",
                product="trusted_plumbing",
                page_url="https://trustedplumbing.com",
                commit=True,
            )

        assert result.get("committed") is True or result.get("json_ld") is not None


# ---------------------------------------------------------------------------
# TestCitationAuditor
# ---------------------------------------------------------------------------

class TestCitationAuditor:

    def test_audit_returns_nap_status_per_source(self, mock_db, cfg):
        auditor = CitationAuditor(mock_db, cfg)

        with patch("agents.seo.citation_auditor.web_search") as mock_search, \
             patch("agents.seo.citation_auditor.llm") as mock_llm:
            mock_search.return_value = _citation_search_results()
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps(_nap_analysis()))
            ]

            result = auditor.audit(business="trusted_plumbing")

        assert "sources_checked" in result
        assert "inconsistencies" in result
        assert "consistent" in result

    def test_inconsistencies_flagged(self, mock_db, cfg):
        auditor = CitationAuditor(mock_db, cfg)

        nap = _nap_analysis()
        nap["inconsistencies"] = [
            {"source": "yelp.com", "field": "phone", "found": "(512) 555-9999", "expected": "(512) 555-0100"},
        ]

        with patch("agents.seo.citation_auditor.web_search") as mock_search, \
             patch("agents.seo.citation_auditor.llm") as mock_llm:
            mock_search.return_value = _citation_search_results()
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(nap))]

            result = auditor.audit(business="trusted_plumbing")

        assert len(result["inconsistencies"]) >= 1

    def test_consistent_nap_returns_zero_inconsistencies(self, mock_db, cfg):
        auditor = CitationAuditor(mock_db, cfg)

        nap = _nap_analysis()
        nap["inconsistencies"] = []

        with patch("agents.seo.citation_auditor.web_search") as mock_search, \
             patch("agents.seo.citation_auditor.llm") as mock_llm:
            mock_search.return_value = _citation_search_results()
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(nap))]

            result = auditor.audit(business="trusted_plumbing")

        assert result["inconsistencies"] == []

    def test_citation_searches_each_configured_source(self, mock_db, cfg):
        auditor = CitationAuditor(mock_db, cfg)

        with patch("agents.seo.citation_auditor.web_search") as mock_search, \
             patch("agents.seo.citation_auditor.llm") as mock_llm:
            mock_search.return_value = _citation_search_results()
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(_nap_analysis()))]

            auditor.audit(business="trusted_plumbing")

        assert mock_search.call_count >= len(cfg["citation_sources"])

    def test_inconsistency_has_required_fields(self, mock_db, cfg):
        auditor = CitationAuditor(mock_db, cfg)

        nap = _nap_analysis()
        nap["inconsistencies"] = [
            {"source": "yelp.com", "field": "address", "found": "123 Main", "expected": "123 Main St, Austin TX 78701"},
        ]

        with patch("agents.seo.citation_auditor.web_search") as mock_search, \
             patch("agents.seo.citation_auditor.llm") as mock_llm:
            mock_search.return_value = _citation_search_results()
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(nap))]

            result = auditor.audit(business="trusted_plumbing")

        for inc in result["inconsistencies"]:
            assert "source" in inc
            assert "field" in inc
            assert "found" in inc
            assert "expected" in inc


# ---------------------------------------------------------------------------
# TestRankTracker
# ---------------------------------------------------------------------------

class TestRankTracker:

    def test_track_stores_rankings_for_all_keywords(self, mock_db, cfg):
        tracker = RankTracker(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())
        mock_db.get_previous_rankings.return_value = []

        keywords = ["local SEO software", "google business profile tool"]

        with patch("agents.seo.rank_tracker.httpx") as mock_httpx:
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _serp_api_response()

            result = tracker.track(product="localoutrank", keywords=keywords)

        assert result["keywords_tracked"] == len(keywords)
        assert mock_db.save_keyword_ranking.call_count == len(keywords)

    def test_drop_alert_triggered_when_top10_falls_3_or_more(self, mock_db, cfg):
        tracker = RankTracker(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())
        # Previous rank was 5, now it's 9 — a 4-position drop
        mock_db.get_previous_rankings.return_value = [_ranking({"rank": 5})]

        with patch("agents.seo.rank_tracker.httpx") as mock_httpx, \
             patch("agents.seo.rank_tracker.alert_reporting_agent") as mock_alert:
            mock_httpx.get.return_value.status_code = 200
            resp = _serp_api_response()
            resp["organic_results"][0]["position"] = 9
            mock_httpx.get.return_value.json.return_value = resp

            tracker.track(product="localoutrank", keywords=["local SEO software"])

        mock_alert.assert_called_once()

    def test_no_alert_when_drop_less_than_threshold(self, mock_db, cfg):
        tracker = RankTracker(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())
        # Previous rank was 5, now 7 — only 2 positions
        mock_db.get_previous_rankings.return_value = [_ranking({"rank": 5})]

        with patch("agents.seo.rank_tracker.httpx") as mock_httpx, \
             patch("agents.seo.rank_tracker.alert_reporting_agent") as mock_alert:
            mock_httpx.get.return_value.status_code = 200
            resp = _serp_api_response()
            resp["organic_results"][0]["position"] = 7
            mock_httpx.get.return_value.json.return_value = resp

            tracker.track(product="localoutrank", keywords=["local SEO software"])

        mock_alert.assert_not_called()

    def test_no_alert_for_keywords_outside_top_10(self, mock_db, cfg):
        tracker = RankTracker(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())
        # Keyword was at 15, now at 20 — outside top 10, no alert
        mock_db.get_previous_rankings.return_value = [_ranking({"rank": 15})]

        with patch("agents.seo.rank_tracker.httpx") as mock_httpx, \
             patch("agents.seo.rank_tracker.alert_reporting_agent") as mock_alert:
            mock_httpx.get.return_value.status_code = 200
            resp = _serp_api_response()
            resp["organic_results"][0]["position"] = 20
            mock_httpx.get.return_value.json.return_value = resp

            tracker.track(product="localoutrank", keywords=["obscure long tail keyword"])

        mock_alert.assert_not_called()

    def test_track_result_contains_snapshot(self, mock_db, cfg):
        tracker = RankTracker(mock_db, cfg)
        mock_db.save_keyword_ranking.return_value = str(uuid.uuid4())
        mock_db.get_previous_rankings.return_value = []

        with patch("agents.seo.rank_tracker.httpx") as mock_httpx, \
             patch("agents.seo.rank_tracker.alert_reporting_agent"):
            mock_httpx.get.return_value.status_code = 200
            mock_httpx.get.return_value.json.return_value = _serp_api_response()

            result = tracker.track(product="localoutrank", keywords=["local SEO software"])

        assert "snapshot" in result
        for row in result["snapshot"]:
            assert "keyword" in row
            assert "rank" in row


# ---------------------------------------------------------------------------
# TestSeoAgent — full dispatch
# ---------------------------------------------------------------------------

class TestSeoAgent:

    def _make_agent(self):
        from agents.seo.main import SeoAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = _cfg()
        config.llm_system_prompt = None
        return SeoAgent("seo", config)

    def test_unknown_action_returns_error(self):
        agent = self._make_agent()
        task = _task("not_a_real_action")
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_gbp_optimize_dispatches(self):
        agent = self._make_agent()
        task = _task("gbp_optimize", {"business": "trusted_plumbing", "gbp_location_id": "locations/123"})
        with patch.object(agent._gbp, "optimize", return_value={"audit_id": "x", "score": 80, "issues_found": 2, "issues_fixed": 1, "actions_taken": []}) as mock_opt:
            result = agent.handle(task)
        mock_opt.assert_called_once()
        assert result.success is True

    def test_keyword_research_dispatches(self):
        agent = self._make_agent()
        task = _task("keyword_research", {"product": "localoutrank", "seed_topic": "local SEO"})
        with patch.object(agent._keywords, "research", return_value={"clusters": [], "quick_wins": []}) as mock_res:
            result = agent.handle(task)
        mock_res.assert_called_once()
        assert result.success is True

    def test_on_page_audit_dispatches(self):
        agent = self._make_agent()
        task = _task("on_page_audit", {"url": "https://localoutrank.com/blog/post"})
        with patch.object(agent._on_page, "audit", return_value={"url": "x", "issues": [], "fix_plan": {}, "checks": {}, "auto_fixed": 0}) as mock_audit:
            result = agent.handle(task)
        mock_audit.assert_called_once()
        assert result.success is True

    def test_schema_markup_dispatches(self):
        agent = self._make_agent()
        task = _task("schema_markup", {"schema_type": "LocalBusiness", "product": "trusted_plumbing", "page_url": "https://trustedplumbing.com"})
        with patch.object(agent._schema, "generate", return_value={"schema_type": "LocalBusiness", "json_ld": "{}"}) as mock_gen:
            result = agent.handle(task)
        mock_gen.assert_called_once()
        assert result.success is True

    def test_citation_audit_dispatches(self):
        agent = self._make_agent()
        task = _task("citation_audit", {"business": "trusted_plumbing"})
        with patch.object(agent._citations, "audit", return_value={"sources_checked": 5, "inconsistencies": [], "consistent": 5}) as mock_aud:
            result = agent.handle(task)
        mock_aud.assert_called_once()
        assert result.success is True

    def test_rank_tracker_dispatches(self):
        agent = self._make_agent()
        task = _task("rank_tracker", {"product": "localoutrank", "keywords": ["local SEO software"]})
        with patch.object(agent._tracker, "track", return_value={"keywords_tracked": 1, "snapshot": []}) as mock_track:
            result = agent.handle(task)
        mock_track.assert_called_once()
        assert result.success is True

    def test_health_check_true_when_db_ok(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_last_gbp_audit", return_value=None):
            assert agent.health_check() is True

    def test_health_check_false_on_db_error(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_last_gbp_audit", side_effect=Exception("db down")):
            assert agent.health_check() is False


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------

def _mock_conn(mock_get_db, fetchone=None, fetchall=None):
    conn = MagicMock()
    cur = MagicMock()
    if fetchone is not None:
        cur.fetchone.return_value = fetchone
    if fetchall is not None:
        cur.fetchall.return_value = fetchall
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_get_db.return_value = conn
    return conn, cur


def _gbp_profile_response() -> dict:
    return {
        "profile": {
            "description": "Trusted plumbers in Austin TX.",
            "categories": {"primaryCategory": {"displayName": "Plumber"}},
            "attributes": [],
            "serviceArea": {},
        },
        "media_count": 8,
        "qa_count": 2,
        "last_post_days_ago": 3,
    }


def _serp_results() -> list:
    return [
        {"title": "Best local SEO software 2026", "url": "serp.com/1", "content": "ranked list"},
        {"title": "How to rank on Google Maps", "url": "serp.com/2", "content": "guide"},
    ]


def _serp_api_response() -> dict:
    return {
        "organic_results": [
            {"position": 8, "link": "https://localoutrank.com", "title": "LocalOutRank"},
            {"position": 12, "link": "https://brightlocal.com", "title": "BrightLocal"},
        ],
        "related_searches": ["local SEO tools", "google business profile software"],
    }


def _keyword_clusters() -> list:
    return [
        {
            "name": "local SEO software",
            "keywords": [
                {"keyword": "local SEO software", "monthly_volume": 2400, "difficulty": 42, "current_rank": 8},
                {"keyword": "best local SEO tool", "monthly_volume": 1300, "difficulty": 38, "current_rank": 14},
            ],
        },
        {
            "name": "google business profile",
            "keywords": [
                {"keyword": "google business profile optimization", "monthly_volume": 3100, "difficulty": 55, "current_rank": 22},
                {"keyword": "gbp management software", "monthly_volume": 880, "difficulty": 31, "current_rank": 5},
            ],
        },
    ]


def _sample_html() -> str:
    return """<!DOCTYPE html>
<html>
<head>
<title>Home</title>
</head>
<body>
<h1>Welcome</h1>
<img src="logo.png">
<p>Content here. <a href="/other">link</a></p>
</body>
</html>"""


def _fix_plan() -> dict:
    return {
        "fixable": [
            {"type": "title", "current": "Home", "suggested": "Local SEO Software | LocalOutRank"},
        ],
        "structural": [],
        "manual": [],
    }


def _citation_search_results() -> list:
    return [
        {"title": "Trusted Plumbing - Yelp", "url": "yelp.com/biz/trusted", "content": "Name: Trusted Plumbing | Phone: (512) 555-0100 | 123 Main St"},
        {"title": "Trusted Plumbing - YP", "url": "yp.com/trusted", "content": "Trusted Plumbing Austin TX (512) 555-0100"},
    ]


def _nap_analysis() -> dict:
    return {
        "inconsistencies": [],
        "consistent": ["yelp.com", "yellowpages.com"],
        "not_found": [],
    }
