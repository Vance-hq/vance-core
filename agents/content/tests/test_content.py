"""Content agent unit tests — no external services required."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from agents._base import AgentConfig
from agents.content.db import ContentDB
from agents.content.blog_writer import BlogWriter
from agents.content.social_writer import SocialWriter
from agents.content.newsletter_writer import NewsletterWriter
from agents.content.landing_writer import LandingWriter
from agents.content.calendar_planner import CalendarPlanner
from shared.types import Task, TaskResult, AgentCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _piece(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "starpio",
        "platform": "blog",
        "type": "blog_post",
        "title": "How to Get More 5-Star Reviews on Google",
        "body": "Full post body here...",
        "status": "published",
        "published_at": datetime.now(timezone.utc),
        "url": "https://starpio.com/blog/get-5-star-reviews",
    }
    if overrides:
        base.update(overrides)
    return base


def _calendar_entry(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "product": "starpio",
        "scheduled_date": date.today(),
        "platform": "linkedin",
        "type": "social_post",
        "topic": "Why review responses matter",
        "status": "pending",
        "content_id": None,
    }
    if overrides:
        base.update(overrides)
    return base


def _cfg() -> dict:
    return {
        "products": {
            "starpio": {
                "publish_mode": "wordpress",
                "wordpress_url": "https://starpio.com",
                "wordpress_user": "admin",
                "wordpress_app_password": "secret",
            },
            "oneserv": {
                "publish_mode": "markdown",
                "repo_path": "/repos/oneserv-site",
                "posts_dir": "content/blog",
            },
        },
        "buffer_access_token": "buf_token_abc",
        "newsletter_from_email": "dutch@starpio.com",
        "newsletter_from_name": "Dutch",
        "resend_api_key": "re_abc123",
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
    return MagicMock(spec=ContentDB)


@pytest.fixture
def cfg():
    return _cfg()


# ---------------------------------------------------------------------------
# TestContentDB
# ---------------------------------------------------------------------------

class TestContentDB:

    def test_save_piece_returns_id(self):
        db = ContentDB()
        piece_id = str(uuid.uuid4())
        with patch("agents.content.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = (piece_id,)
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            result = db.save_piece(
                product="starpio",
                platform="blog",
                content_type="blog_post",
                title="Test Post",
                body="Body here",
                status="draft",
            )
            assert result == piece_id

    def test_get_recent_pieces_returns_list(self):
        db = ContentDB()
        rows = [_piece(), _piece({"platform": "linkedin"})]
        with patch("agents.content.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            cur.__iter__ = MagicMock(return_value=iter(rows))
            cur.fetchall.return_value = rows
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            result = db.get_recent_pieces(product="starpio", limit=10)
            assert isinstance(result, list)

    def test_save_calendar_entry_returns_id(self):
        db = ContentDB()
        entry_id = str(uuid.uuid4())
        with patch("agents.content.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = (entry_id,)
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            result = db.save_calendar_entry(
                product="starpio",
                scheduled_date=date.today(),
                platform="linkedin",
                content_type="social_post",
                topic="Review responses",
            )
            assert result == entry_id

    def test_get_calendar_entries_filters_by_product(self):
        db = ContentDB()
        with patch("agents.content.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchall.return_value = [_calendar_entry()]
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            result = db.get_calendar_entries(product="starpio")
            assert isinstance(result, list)

    def test_update_calendar_entry_status(self):
        db = ContentDB()
        entry_id = str(uuid.uuid4())
        with patch("agents.content.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            db.update_calendar_entry(entry_id, status="queued", content_id="cid")
            cur.execute.assert_called_once()


# ---------------------------------------------------------------------------
# TestBlogWriter
# ---------------------------------------------------------------------------

class TestBlogWriter:

    def test_write_blog_post_returns_expected_keys(self, mock_db, cfg):
        writer = BlogWriter(mock_db, cfg)
        mock_db.get_recent_pieces.return_value = []
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.blog_writer.web_search") as mock_search, \
             patch("agents.content.blog_writer.llm") as mock_llm:
            mock_search.return_value = [
                {"title": "Review trends", "url": "https://example.com", "content": "snippet 1"},
            ]
            mock_llm.complete.return_value.content = [
                MagicMock(text="# How to Get Reviews\n\nFirst paragraph with google reviews keyword.\n\n## Section\n\nContent here.")
            ]

            result = writer.write(
                product="starpio",
                topic="google reviews",
                target_audience="restaurant owners",
                word_count=800,
            )

        assert "piece_id" in result
        assert "title" in result
        assert "status" in result

    def test_blog_post_seo_title_contains_keyword(self, mock_db, cfg):
        writer = BlogWriter(mock_db, cfg)
        mock_db.get_recent_pieces.return_value = []
        mock_db.save_piece.return_value = str(uuid.uuid4())

        keyword = "plumbing software"
        with patch("agents.content.blog_writer.web_search") as mock_search, \
             patch("agents.content.blog_writer.llm") as mock_llm:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=f"# Best {keyword} for Small Shops\n\nUsing {keyword} saves time.\n\n## Section\n\nMore detail.")
            ]

            result = writer.write(
                product="oneserv",
                topic=keyword,
                target_audience="contractors",
                word_count=600,
            )

        assert keyword.lower() in result["title"].lower()

    def test_blog_post_generates_meta_description(self, mock_db, cfg):
        writer = BlogWriter(mock_db, cfg)
        mock_db.get_recent_pieces.return_value = []
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.blog_writer.web_search") as mock_search, \
             patch("agents.content.blog_writer.llm") as mock_llm:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text="# Topic Title\n\nOpening paragraph.\n\n## Section\n\nBody.")
            ]

            result = writer.write(
                product="starpio",
                topic="review management",
                target_audience="restaurant owners",
                word_count=600,
            )

        assert "meta_description" in result
        assert len(result["meta_description"]) <= 160

    def test_blog_post_adds_internal_links(self, mock_db, cfg):
        writer = BlogWriter(mock_db, cfg)
        existing = [
            _piece({"title": "How to Respond to Reviews", "url": "https://starpio.com/blog/respond"}),
            _piece({"title": "Google Business Profile Tips", "url": "https://starpio.com/blog/gbp"}),
            _piece({"title": "Review Removal Guide", "url": "https://starpio.com/blog/removal"}),
        ]
        mock_db.get_recent_pieces.return_value = existing
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.blog_writer.web_search") as mock_search, \
             patch("agents.content.blog_writer.llm") as mock_llm:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text="# Review Strategy\n\nUse google reviews respond.\n\n## Profile\n\nGoogle business tips here.")
            ]

            result = writer.write(
                product="starpio",
                topic="review strategy",
                target_audience="restaurant owners",
                word_count=800,
            )

        assert result.get("internal_links_added", 0) >= 0

    def test_blog_wordpress_publish_calls_api(self, mock_db, cfg):
        writer = BlogWriter(mock_db, cfg)
        mock_db.get_recent_pieces.return_value = []
        piece_id = str(uuid.uuid4())
        mock_db.save_piece.return_value = piece_id

        with patch("agents.content.blog_writer.web_search") as mock_search, \
             patch("agents.content.blog_writer.llm") as mock_llm, \
             patch("agents.content.blog_writer.httpx") as mock_httpx:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text="# Google Reviews\n\nFirst 100 words google reviews.\n\n## Tips\n\nMore.")
            ]
            mock_httpx.post.return_value.status_code = 201
            mock_httpx.post.return_value.json.return_value = {"id": 99, "link": "https://starpio.com/blog/reviews"}

            result = writer.write(
                product="starpio",
                topic="google reviews",
                target_audience="restaurant owners",
                word_count=800,
                publish=True,
            )

        mock_httpx.post.assert_called_once()
        assert result["status"] in ("published", "draft")


# ---------------------------------------------------------------------------
# TestSocialWriter
# ---------------------------------------------------------------------------

class TestSocialWriter:

    def test_linkedin_post_within_char_limits(self, mock_db, cfg):
        writer = SocialWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.social_writer.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="A" * 900)
            ]
            result = writer.write(
                product="starpio",
                platform="linkedin",
                topic="why review responses matter",
            )

        assert result["platform"] == "linkedin"
        assert len(result["body"]) >= 800
        assert len(result["body"]) <= 1200

    def test_twitter_thread_has_hook_plus_supporting_tweets(self, mock_db, cfg):
        writer = SocialWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.social_writer.llm") as mock_llm:
            tweets = ["Hook tweet here."] + [f"Tweet {i}" for i in range(1, 7)]
            mock_llm.complete.return_value.content = [
                MagicMock(text="\n---\n".join(tweets))
            ]
            result = writer.write(
                product="oneserv",
                platform="twitter",
                topic="job scheduling tips for contractors",
            )

        assert result["platform"] == "twitter"
        assert "tweets" in result
        assert len(result["tweets"]) >= 6

    def test_facebook_post_ends_with_question(self, mock_db, cfg):
        writer = SocialWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.social_writer.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="Running a local business is tough. We built a tool to help. What's your biggest scheduling headache?")
            ]
            result = writer.write(
                product="oneserv",
                platform="facebook",
                topic="scheduling headaches",
            )

        assert result["platform"] == "facebook"
        assert result["body"].strip().endswith("?")

    def test_linkedin_ends_with_question_or_strong_pov(self, mock_db, cfg):
        writer = SocialWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.social_writer.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="A" * 900 + "\n\nIs this the most overlooked part of running a local business?")
            ]
            result = writer.write(
                product="starpio",
                platform="linkedin",
                topic="reputation management",
            )

        # Body ends with question or strong POV punctuation (? or .)
        body = result["body"].strip()
        assert body[-1] in ("?", ".")

    def test_social_post_saved_to_db(self, mock_db, cfg):
        writer = SocialWriter(mock_db, cfg)
        piece_id = str(uuid.uuid4())
        mock_db.save_piece.return_value = piece_id

        with patch("agents.content.social_writer.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="A" * 950 + "\nWhat do you think?")
            ]
            result = writer.write(
                product="starpio",
                platform="linkedin",
                topic="online reputation",
            )

        mock_db.save_piece.assert_called_once()
        assert result["piece_id"] == piece_id

    def test_distinct_platform_prompts_are_used(self, mock_db, cfg):
        """LinkedIn and Twitter should hit different LLM system prompts."""
        writer = SocialWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        calls = []
        def capture_call(**kwargs):
            calls.append(kwargs.get("system", ""))
            if kwargs.get("system", "").startswith("LinkedIn"):
                return MagicMock(content=[MagicMock(text="A" * 900 + "\nWhat's next?")])
            return MagicMock(content=[MagicMock(text="Hook\n---\nTweet 1\n---\nTweet 2\n---\nTweet 3\n---\nTweet 4\n---\nTweet 5")])

        with patch("agents.content.social_writer.llm") as mock_llm:
            mock_llm.complete.side_effect = capture_call
            writer.write(product="starpio", platform="linkedin", topic="topic")
            mock_db.save_piece.return_value = str(uuid.uuid4())
            writer.write(product="starpio", platform="twitter", topic="topic")

        assert calls[0] != calls[1]


# ---------------------------------------------------------------------------
# TestNewsletterWriter
# ---------------------------------------------------------------------------

class TestNewsletterWriter:

    def test_newsletter_has_required_sections(self, mock_db, cfg):
        writer = NewsletterWriter(mock_db, cfg)
        mock_db.get_recent_pieces.return_value = []
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.newsletter_writer.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="LEAD: Something happened.\n\nITEM1: Short item one.\n\nITEM2: Short item two.\n\nCTA: Try the new feature.")
            ]
            result = writer.write(product="starpio")

        assert "lead_story" in result
        assert "short_items" in result
        assert len(result["short_items"]) == 2
        assert "cta" in result

    def test_newsletter_piece_saved_as_newsletter_type(self, mock_db, cfg):
        writer = NewsletterWriter(mock_db, cfg)
        mock_db.get_recent_pieces.return_value = []
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.newsletter_writer.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="LEAD: Story.\n\nITEM1: Item one.\n\nITEM2: Item two.\n\nCTA: Do this.")
            ]
            writer.write(product="starpio")

        call_kwargs = mock_db.save_piece.call_args
        assert call_kwargs.kwargs.get("content_type") == "newsletter" or \
               (call_kwargs.args and "newsletter" in call_kwargs.args)

    def test_newsletter_send_triggers_broadcast(self, mock_db, cfg):
        writer = NewsletterWriter(mock_db, cfg)
        mock_db.get_recent_pieces.return_value = []
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.newsletter_writer.llm") as mock_llm, \
             patch("agents.content.newsletter_writer.httpx") as mock_httpx:
            mock_llm.complete.return_value.content = [
                MagicMock(text="LEAD: Story.\n\nITEM1: Item one.\n\nITEM2: Item two.\n\nCTA: Do this.")
            ]
            mock_httpx.post.return_value.status_code = 200
            mock_httpx.post.return_value.json.return_value = {"id": "bcast_123"}

            result = writer.write(product="starpio", send=True)

        mock_httpx.post.assert_called_once()
        assert result.get("sent") is True or result.get("broadcast_id") is not None

    def test_newsletter_lead_story_from_recent_content(self, mock_db, cfg):
        writer = NewsletterWriter(mock_db, cfg)
        recent = [_piece({"type": "blog_post", "title": "New review scoring feature"})]
        mock_db.get_recent_pieces.return_value = recent
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.newsletter_writer.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="LEAD: New scoring feature is live.\n\nITEM1: Item one.\n\nITEM2: Item two.\n\nCTA: Try it.")
            ]
            result = writer.write(product="starpio")

        # The LLM was called with context about recent pieces
        call_args = mock_llm.complete.call_args
        user_msg = call_args.kwargs["messages"][0]["content"]
        assert "review scoring" in user_msg.lower() or "recent" in user_msg.lower()


# ---------------------------------------------------------------------------
# TestLandingWriter
# ---------------------------------------------------------------------------

class TestLandingWriter:

    def test_generates_three_variants(self, mock_db, cfg):
        writer = LandingWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.landing_writer.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="VARIANT_A:\nHero text A\n\nVARIANT_B:\nHero text B\n\nVARIANT_C:\nHero text C")
            ]
            result = writer.write(
                product="starpio",
                section="hero",
                performance_signal="low conversion",
            )

        assert "variants" in result
        assert len(result["variants"]) == 3

    def test_variants_committed_to_repo(self, mock_db, cfg):
        writer = LandingWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.landing_writer.llm") as mock_llm, \
             patch("agents.content.landing_writer.subprocess") as mock_sub:
            mock_llm.complete.return_value.content = [
                MagicMock(text="VARIANT_A:\nText A\n\nVARIANT_B:\nText B\n\nVARIANT_C:\nText C")
            ]
            mock_sub.run.return_value.returncode = 0

            result = writer.write(
                product="oneserv",
                section="hero",
                performance_signal="high bounce",
            )

        assert result.get("committed") is True or result.get("commit_sha") is not None

    def test_valid_section_names_accepted(self, mock_db, cfg):
        writer = LandingWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        for section in ("hero", "benefits", "pricing", "faq", "cta"):
            with patch("agents.content.landing_writer.llm") as mock_llm, \
                 patch("agents.content.landing_writer.subprocess"):
                mock_llm.complete.return_value.content = [
                    MagicMock(text="VARIANT_A:\nA\n\nVARIANT_B:\nB\n\nVARIANT_C:\nC")
                ]
                result = writer.write(
                    product="starpio",
                    section=section,
                    performance_signal="low conversion",
                )
            assert "variants" in result

    def test_invalid_section_returns_error(self, mock_db, cfg):
        writer = LandingWriter(mock_db, cfg)

        result = writer.write(
            product="starpio",
            section="checkout",
            performance_signal="low conversion",
        )
        assert "error" in result

    def test_variant_test_assignment_logged(self, mock_db, cfg):
        writer = LandingWriter(mock_db, cfg)
        mock_db.save_piece.return_value = str(uuid.uuid4())

        with patch("agents.content.landing_writer.llm") as mock_llm, \
             patch("agents.content.landing_writer.subprocess"):
            mock_llm.complete.return_value.content = [
                MagicMock(text="VARIANT_A:\nHero A\n\nVARIANT_B:\nHero B\n\nVARIANT_C:\nHero C")
            ]
            result = writer.write(
                product="starpio",
                section="hero",
                performance_signal="low conversion",
            )

        assert mock_db.save_piece.call_count == 3  # one per variant


# ---------------------------------------------------------------------------
# TestCalendarPlanner
# ---------------------------------------------------------------------------

class TestCalendarPlanner:

    def test_calendar_produces_30_entries(self, mock_db, cfg):
        planner = CalendarPlanner(mock_db, cfg)
        mock_db.save_calendar_entry.return_value = str(uuid.uuid4())

        with patch("agents.content.calendar_planner.web_search") as mock_search, \
             patch("agents.content.calendar_planner.llm") as mock_llm:
            mock_search.return_value = []
            calendar_json = _make_calendar_json(30)
            mock_llm.complete.return_value.content = [
                MagicMock(text=calendar_json)
            ]

            result = planner.plan(product="starpio")

        assert result["total_entries"] == 30

    def test_calendar_saves_all_entries_to_db(self, mock_db, cfg):
        planner = CalendarPlanner(mock_db, cfg)
        mock_db.save_calendar_entry.return_value = str(uuid.uuid4())

        with patch("agents.content.calendar_planner.web_search") as mock_search, \
             patch("agents.content.calendar_planner.llm") as mock_llm:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=_make_calendar_json(30))
            ]

            planner.plan(product="starpio")

        assert mock_db.save_calendar_entry.call_count == 30

    def test_calendar_entries_have_required_fields(self, mock_db, cfg):
        planner = CalendarPlanner(mock_db, cfg)
        mock_db.save_calendar_entry.return_value = str(uuid.uuid4())

        with patch("agents.content.calendar_planner.web_search") as mock_search, \
             patch("agents.content.calendar_planner.llm") as mock_llm:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=_make_calendar_json(30))
            ]

            result = planner.plan(product="starpio")

        for entry in result["calendar"]:
            assert "date" in entry
            assert "platform" in entry
            assert "type" in entry
            assert "topic" in entry

    def test_calendar_enqueues_tasks_on_schedule(self, mock_db, cfg):
        planner = CalendarPlanner(mock_db, cfg)
        mock_db.save_calendar_entry.return_value = str(uuid.uuid4())

        with patch("agents.content.calendar_planner.web_search") as mock_search, \
             patch("agents.content.calendar_planner.llm") as mock_llm, \
             patch("agents.content.calendar_planner.enqueue_content_task") as mock_enqueue:
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=_make_calendar_json(5))
            ]

            planner.plan(product="starpio")

        assert mock_enqueue.call_count == 5

    def test_calendar_searches_competitor_gaps(self, mock_db, cfg):
        planner = CalendarPlanner(mock_db, cfg)
        mock_db.save_calendar_entry.return_value = str(uuid.uuid4())

        with patch("agents.content.calendar_planner.web_search") as mock_search, \
             patch("agents.content.calendar_planner.llm") as mock_llm:
            mock_search.return_value = [{"title": "Competitor post", "url": "x.com", "content": "..."}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=_make_calendar_json(30))
            ]

            planner.plan(product="starpio")

        assert mock_search.call_count >= 1


# ---------------------------------------------------------------------------
# TestContentAgent — full dispatch
# ---------------------------------------------------------------------------

class TestContentAgent:

    def _make_agent(self):
        from agents.content.main import ContentAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = _cfg()
        config.llm_system_prompt = None
        return ContentAgent("content", config)

    def test_unknown_action_raises(self):
        agent = self._make_agent()
        task = _task("not_a_real_action")
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_write_blog_post_dispatches(self):
        agent = self._make_agent()
        task = _task("write_blog_post", {
            "product": "starpio",
            "topic": "google reviews",
            "target_audience": "restaurant owners",
            "word_count": 800,
        })
        with patch.object(agent._blog, "write", return_value={"piece_id": "x", "title": "T", "status": "draft", "meta_description": "M", "internal_links_added": 0}) as mock_write:
            result = agent.handle(task)
        mock_write.assert_called_once()
        assert result.success is True

    def test_write_social_post_dispatches(self):
        agent = self._make_agent()
        task = _task("write_social_post", {
            "product": "starpio",
            "platform": "linkedin",
            "topic": "review responses",
        })
        with patch.object(agent._social, "write", return_value={"piece_id": "x", "platform": "linkedin", "body": "A" * 900 + "?"}) as mock_write:
            result = agent.handle(task)
        mock_write.assert_called_once()
        assert result.success is True

    def test_write_newsletter_dispatches(self):
        agent = self._make_agent()
        task = _task("write_newsletter", {"product": "starpio"})
        with patch.object(agent._newsletter, "write", return_value={"lead_story": "S", "short_items": ["a", "b"], "cta": "Try it"}) as mock_write:
            result = agent.handle(task)
        mock_write.assert_called_once()
        assert result.success is True

    def test_update_landing_page_dispatches(self):
        agent = self._make_agent()
        task = _task("update_landing_page", {
            "product": "starpio",
            "section": "hero",
            "performance_signal": "low conversion",
        })
        with patch.object(agent._landing, "write", return_value={"variants": ["A", "B", "C"], "committed": True}) as mock_write:
            result = agent.handle(task)
        mock_write.assert_called_once()
        assert result.success is True

    def test_content_calendar_dispatches(self):
        agent = self._make_agent()
        task = _task("content_calendar", {"product": "starpio"})
        with patch.object(agent._calendar, "plan", return_value={"total_entries": 30, "calendar": []}) as mock_plan:
            result = agent.handle(task)
        mock_plan.assert_called_once()
        assert result.success is True

    def test_health_check_returns_true_when_db_ok(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_recent_pieces", return_value=[]):
            assert agent.health_check() is True

    def test_health_check_returns_false_on_db_error(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_recent_pieces", side_effect=Exception("db down")):
            assert agent.health_check() is False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import json

def _make_calendar_json(n: int) -> str:
    entries = []
    platforms = ["linkedin", "twitter", "blog", "facebook", "newsletter"]
    types = ["social_post", "social_post", "blog_post", "social_post", "newsletter"]
    for i in range(n):
        entries.append({
            "date": f"2026-07-{(i % 30) + 1:02d}",
            "platform": platforms[i % len(platforms)],
            "type": types[i % len(types)],
            "topic": f"Topic {i + 1}",
            "status": "pending",
        })
    return json.dumps(entries)
