"""Viral agent unit tests — no external services required."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from agents._base import AgentConfig
from agents.viral.db import ViralDB
from agents.viral.trend_scanner import TrendScanner
from agents.viral.piece_creator import PieceCreator
from agents.viral.hook_generator import HookGenerator
from agents.viral.remix_engine import RemixEngine
from agents.viral.gap_finder import GapFinder
from shared.types import Task, TaskResult, AgentCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trend(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "trend_topic": "Google reviews ranking factor 2026",
        "platform": "twitter",
        "relevance_score": 8.5,
        "velocity": "rising",
        "opportunity_window_hours": 6,
        "detected_at": datetime.now(timezone.utc),
        "acted_on": False,
    }
    if overrides:
        base.update(overrides)
    return base


def _viral_piece(overrides: dict | None = None) -> dict:
    base = {
        "id": str(uuid.uuid4()),
        "trend_id": str(uuid.uuid4()),
        "product": "starpio",
        "platform": "twitter",
        "content": "Full thread content here",
        "hook": "Google just changed the review algorithm. Here's what nobody is telling you.",
        "published_at": datetime.now(timezone.utc),
        "engagement_score": 4.2,
    }
    if overrides:
        base.update(overrides)
    return base


def _cfg() -> dict:
    return {
        "products": ["starpio", "oneserv", "localoutrank", "trusted_plumbing"],
        "apify_api_token": "apify_token_abc",
        "reddit_client_id": "reddit_id",
        "reddit_client_secret": "reddit_secret",
        "relevance_threshold": 7,
        "competitor_blogs": {
            "starpio": ["grade.us/blog", "birdeye.com/blog"],
            "oneserv": ["jobber.com/blog", "housecallpro.com/blog"],
            "localoutrank": ["brightlocal.com/blog", "whitespark.ca/blog"],
        },
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
    return MagicMock(spec=ViralDB)


@pytest.fixture
def cfg():
    return _cfg()


# ---------------------------------------------------------------------------
# TestViralDB
# ---------------------------------------------------------------------------

class TestViralDB:

    def test_save_trend_returns_id(self):
        db = ViralDB()
        trend_id = str(uuid.uuid4())
        with patch("agents.viral.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = (trend_id,)
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            result = db.save_trend(
                trend_topic="AI review responses",
                platform="twitter",
                relevance_score=8.0,
                velocity="rising",
                opportunity_window_hours=4,
            )
            assert result == trend_id

    def test_get_recent_trends_returns_list(self):
        db = ViralDB()
        rows = [_trend(), _trend({"platform": "reddit"})]
        with patch("agents.viral.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchall.return_value = rows
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            result = db.get_recent_trends(hours=24)
            assert isinstance(result, list)

    def test_save_viral_piece_returns_id(self):
        db = ViralDB()
        piece_id = str(uuid.uuid4())
        with patch("agents.viral.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = (piece_id,)
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            result = db.save_viral_piece(
                trend_id=str(uuid.uuid4()),
                product="starpio",
                platform="twitter",
                content="Thread content here",
                hook="Hook sentence",
            )
            assert result == piece_id

    def test_get_top_pieces_by_engagement(self):
        db = ViralDB()
        rows = [_viral_piece({"engagement_score": 9.1}), _viral_piece({"engagement_score": 7.4})]
        with patch("agents.viral.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchall.return_value = rows
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            result = db.get_top_pieces(product="starpio", days=30, limit=5)
            assert isinstance(result, list)

    def test_mark_trend_acted_on(self):
        db = ViralDB()
        trend_id = str(uuid.uuid4())
        with patch("agents.viral.db.get_db") as mock_get_db:
            conn = MagicMock()
            cur = MagicMock()
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
            conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
            mock_get_db.return_value = conn

            db.mark_trend_acted_on(trend_id)
            cur.execute.assert_called_once()


# ---------------------------------------------------------------------------
# TestTrendScanner
# ---------------------------------------------------------------------------

class TestTrendScanner:

    def test_scan_returns_list_of_trends(self, mock_db, cfg):
        scanner = TrendScanner(mock_db, cfg)
        mock_db.save_trend.return_value = str(uuid.uuid4())

        with patch("agents.viral.trend_scanner.web_search") as mock_search, \
             patch("agents.viral.trend_scanner.llm") as mock_llm:
            mock_search.return_value = [
                {"title": "Google reviews update", "url": "x.com/1", "content": "Big changes"},
            ]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"topic": "Google reviews update", "relevance": 8, "velocity": "rising", "window_hours": 6},
                ]))
            ]

            result = scanner.scan(product="starpio")

        assert isinstance(result, list)
        assert len(result) >= 0

    def test_high_relevance_rising_trend_enqueues_piece(self, mock_db, cfg):
        scanner = TrendScanner(mock_db, cfg)
        mock_db.save_trend.return_value = str(uuid.uuid4())

        with patch("agents.viral.trend_scanner.web_search") as mock_search, \
             patch("agents.viral.trend_scanner.llm") as mock_llm, \
             patch("agents.viral.trend_scanner.enqueue_viral_piece") as mock_enqueue:
            mock_search.return_value = [
                {"title": "AI review tools going viral", "url": "x.com/1", "content": "Trending now"},
            ]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"topic": "AI review tools", "relevance": 9, "velocity": "rising", "window_hours": 4},
                ]))
            ]

            scanner.scan(product="starpio")

        mock_enqueue.assert_called_once()

    def test_low_relevance_trend_does_not_enqueue(self, mock_db, cfg):
        scanner = TrendScanner(mock_db, cfg)
        mock_db.save_trend.return_value = str(uuid.uuid4())

        with patch("agents.viral.trend_scanner.web_search") as mock_search, \
             patch("agents.viral.trend_scanner.llm") as mock_llm, \
             patch("agents.viral.trend_scanner.enqueue_viral_piece") as mock_enqueue:
            mock_search.return_value = [
                {"title": "Celebrity gossip", "url": "x.com/2", "content": "Unrelated"},
            ]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"topic": "Celebrity gossip", "relevance": 2, "velocity": "rising", "window_hours": 2},
                ]))
            ]

            scanner.scan(product="starpio")

        mock_enqueue.assert_not_called()

    def test_peak_or_declining_trend_does_not_enqueue(self, mock_db, cfg):
        scanner = TrendScanner(mock_db, cfg)
        mock_db.save_trend.return_value = str(uuid.uuid4())

        with patch("agents.viral.trend_scanner.web_search") as mock_search, \
             patch("agents.viral.trend_scanner.llm") as mock_llm, \
             patch("agents.viral.trend_scanner.enqueue_viral_piece") as mock_enqueue:
            mock_search.return_value = [{"title": "Trend", "url": "x.com", "content": "past peak"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"topic": "Some trend", "relevance": 9, "velocity": "declining", "window_hours": 1},
                ]))
            ]

            scanner.scan(product="starpio")

        mock_enqueue.assert_not_called()

    def test_trend_saved_to_db(self, mock_db, cfg):
        scanner = TrendScanner(mock_db, cfg)
        mock_db.save_trend.return_value = str(uuid.uuid4())

        with patch("agents.viral.trend_scanner.web_search") as mock_search, \
             patch("agents.viral.trend_scanner.llm") as mock_llm, \
             patch("agents.viral.trend_scanner.enqueue_viral_piece"):
            mock_search.return_value = [{"title": "Trend A", "url": "x.com", "content": "info"}]
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"topic": "Trend A", "relevance": 8, "velocity": "rising", "window_hours": 5},
                ]))
            ]

            scanner.scan(product="starpio")

        mock_db.save_trend.assert_called_once()

    def test_scan_all_products_iterates_each(self, mock_db, cfg):
        scanner = TrendScanner(mock_db, cfg)
        mock_db.save_trend.return_value = str(uuid.uuid4())

        with patch.object(scanner, "scan", return_value=[]) as mock_scan:
            scanner.scan_all()

        assert mock_scan.call_count == len(cfg["products"])


# ---------------------------------------------------------------------------
# TestPieceCreator
# ---------------------------------------------------------------------------

class TestPieceCreator:

    def test_create_returns_expected_keys(self, mock_db, cfg):
        creator = PieceCreator(mock_db, cfg)
        mock_db.save_viral_piece.return_value = str(uuid.uuid4())

        with patch("agents.viral.piece_creator.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="HOOK: Nobody is talking about this Google change.\n\nPOINT1: Reviews now weight recency.\n\nPOINT2: Response rate is a ranking signal.\n\nPOINT3: Photos on responses help.\n\nCTA: Check your review score at starpio.com")
            ]

            result = creator.create(
                trend_id=str(uuid.uuid4()),
                trend_topic="Google review algorithm update",
                product="starpio",
                platform="twitter",
                opportunity_window_hours=6,
            )

        assert "piece_id" in result
        assert "hook" in result
        assert "content" in result
        assert "platform" in result

    def test_twitter_format_is_thread(self, mock_db, cfg):
        creator = PieceCreator(mock_db, cfg)
        mock_db.save_viral_piece.return_value = str(uuid.uuid4())

        with patch("agents.viral.piece_creator.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="HOOK: The thing about Google reviews.\n\nPOINT1: First point.\n\nPOINT2: Second point.\n\nPOINT3: Third point.\n\nCTA: Try starpio.com")
            ]

            result = creator.create(
                trend_id=str(uuid.uuid4()),
                trend_topic="Google reviews",
                product="starpio",
                platform="twitter",
                opportunity_window_hours=4,
            )

        assert result["format"] == "thread"

    def test_tiktok_format_is_script(self, mock_db, cfg):
        creator = PieceCreator(mock_db, cfg)
        mock_db.save_viral_piece.return_value = str(uuid.uuid4())

        with patch("agents.viral.piece_creator.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="HOOK: Open with this.\n\nPOINT1: First.\n\nPOINT2: Second.\n\nPOINT3: Third.\n\nCTA: Follow for more.")
            ]

            result = creator.create(
                trend_id=str(uuid.uuid4()),
                trend_topic="contractor apps",
                product="oneserv",
                platform="tiktok",
                opportunity_window_hours=3,
            )

        assert result["format"] == "script"

    def test_linkedin_format_is_hot_take(self, mock_db, cfg):
        creator = PieceCreator(mock_db, cfg)
        mock_db.save_viral_piece.return_value = str(uuid.uuid4())

        with patch("agents.viral.piece_creator.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="HOOK: Hot take on local SEO.\n\nPOINT1: First.\n\nPOINT2: Second.\n\nPOINT3: Third.\n\nCTA: What do you think?")
            ]

            result = creator.create(
                trend_id=str(uuid.uuid4()),
                trend_topic="local SEO myth",
                product="localoutrank",
                platform="linkedin",
                opportunity_window_hours=8,
            )

        assert result["format"] == "hot_take"

    def test_piece_uses_distinct_system_prompts_per_platform(self, mock_db, cfg):
        creator = PieceCreator(mock_db, cfg)
        mock_db.save_viral_piece.return_value = str(uuid.uuid4())

        captured_systems = []
        def capture(**kwargs):
            captured_systems.append(kwargs.get("system", ""))
            return MagicMock(content=[MagicMock(text="HOOK: H\n\nPOINT1: A\n\nPOINT2: B\n\nPOINT3: C\n\nCTA: Go")])

        with patch("agents.viral.piece_creator.llm") as mock_llm:
            mock_llm.complete.side_effect = capture
            creator.create(str(uuid.uuid4()), "topic", "starpio", "twitter", 4)
            mock_db.save_viral_piece.return_value = str(uuid.uuid4())
            creator.create(str(uuid.uuid4()), "topic", "starpio", "linkedin", 4)

        assert captured_systems[0] != captured_systems[1]

    def test_viral_piece_saved_to_db(self, mock_db, cfg):
        creator = PieceCreator(mock_db, cfg)
        piece_id = str(uuid.uuid4())
        mock_db.save_viral_piece.return_value = piece_id

        with patch("agents.viral.piece_creator.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="HOOK: The hook.\n\nPOINT1: P1\n\nPOINT2: P2\n\nPOINT3: P3\n\nCTA: Do it.")
            ]

            result = creator.create(str(uuid.uuid4()), "topic", "starpio", "twitter", 4)

        mock_db.save_viral_piece.assert_called_once()
        assert result["piece_id"] == piece_id


# ---------------------------------------------------------------------------
# TestHookGenerator
# ---------------------------------------------------------------------------

class TestHookGenerator:

    def test_returns_ten_hooks(self, mock_db, cfg):
        gen = HookGenerator(cfg)

        with patch("agents.viral.hook_generator.llm") as mock_llm:
            hooks_raw = "\n".join([f"{i+1}. Hook number {i+1}" for i in range(10)])
            mock_llm.complete.return_value.content = [MagicMock(text=hooks_raw)]

            result = gen.generate(
                topic="review management software",
                platform="linkedin",
                tone="educational",
            )

        assert len(result["hooks"]) == 10

    def test_hooks_are_ranked_by_score(self, mock_db, cfg):
        gen = HookGenerator(cfg)

        with patch("agents.viral.hook_generator.llm") as mock_llm:
            hooks_raw = "\n".join([f"{i+1}. Hook {i+1}" for i in range(10)])
            mock_llm.complete.return_value.content = [MagicMock(text=hooks_raw)]

            result = gen.generate(
                topic="local SEO",
                platform="twitter",
                tone="data_driven",
            )

        scores = [h["score"] for h in result["hooks"]]
        assert scores == sorted(scores, reverse=True)

    def test_each_hook_has_rubric_scores(self, mock_db, cfg):
        gen = HookGenerator(cfg)

        with patch("agents.viral.hook_generator.llm") as mock_llm:
            hooks_raw = "\n".join([f"{i+1}. Hook variant {i+1}" for i in range(10)])
            mock_llm.complete.return_value.content = [MagicMock(text=hooks_raw)]

            result = gen.generate(
                topic="contractor scheduling",
                platform="facebook",
                tone="personal_story",
            )

        for hook in result["hooks"]:
            assert "text" in hook
            assert "score" in hook
            assert "specificity" in hook
            assert "curiosity_gap" in hook
            assert "emotional_charge" in hook
            assert "shareability" in hook

    def test_valid_tones_accepted(self, mock_db, cfg):
        gen = HookGenerator(cfg)

        for tone in ("controversial", "educational", "personal_story", "data_driven"):
            with patch("agents.viral.hook_generator.llm") as mock_llm:
                mock_llm.complete.return_value.content = [
                    MagicMock(text="\n".join([f"{i+1}. Hook {i+1}" for i in range(10)]))
                ]
                result = gen.generate(topic="topic", platform="twitter", tone=tone)
            assert len(result["hooks"]) == 10

    def test_invalid_tone_returns_error(self, mock_db, cfg):
        gen = HookGenerator(cfg)
        result = gen.generate(topic="topic", platform="twitter", tone="clickbait")
        assert "error" in result

    def test_top_hook_is_first_in_list(self, mock_db, cfg):
        gen = HookGenerator(cfg)

        with patch("agents.viral.hook_generator.llm") as mock_llm:
            mock_llm.complete.return_value.content = [
                MagicMock(text="\n".join([f"{i+1}. Hook {i+1}" for i in range(10)]))
            ]
            result = gen.generate(topic="topic", platform="linkedin", tone="controversial")

        top = result["hooks"][0]
        assert top["score"] == max(h["score"] for h in result["hooks"])


# ---------------------------------------------------------------------------
# TestRemixEngine
# ---------------------------------------------------------------------------

class TestRemixEngine:

    def test_remix_pulls_top_5_pieces(self, mock_db, cfg):
        engine = RemixEngine(mock_db, cfg)
        top_pieces = [_viral_piece() for _ in range(5)]
        mock_db.get_top_pieces.return_value = top_pieces

        with patch("agents.viral.remix_engine.llm") as mock_llm, \
             patch("agents.viral.remix_engine.enqueue_content_task") as mock_enqueue:
            mock_llm.complete.return_value.content = [
                MagicMock(text="Remixed content for this platform")
            ]

            engine.remix(product="starpio")

        mock_db.get_top_pieces.assert_called_once_with(product="starpio", days=30, limit=5)

    def test_remix_generates_multiple_platform_variants(self, mock_db, cfg):
        engine = RemixEngine(mock_db, cfg)
        mock_db.get_top_pieces.return_value = [_viral_piece({"platform": "linkedin"})]

        remixed = []
        with patch("agents.viral.remix_engine.llm") as mock_llm, \
             patch("agents.viral.remix_engine.enqueue_content_task") as mock_enqueue:
            mock_llm.complete.return_value.content = [
                MagicMock(text="Remixed content")
            ]
            mock_enqueue.side_effect = lambda **kw: remixed.append(kw)

            engine.remix(product="starpio")

        # One LinkedIn piece should produce remixes for other platforms (twitter + tiktok at least)
        assert mock_enqueue.call_count >= 2

    def test_remix_enqueues_to_content_calendar(self, mock_db, cfg):
        engine = RemixEngine(mock_db, cfg)
        mock_db.get_top_pieces.return_value = [_viral_piece()]

        with patch("agents.viral.remix_engine.llm") as mock_llm, \
             patch("agents.viral.remix_engine.enqueue_content_task") as mock_enqueue:
            mock_llm.complete.return_value.content = [
                MagicMock(text="Remixed content")
            ]

            result = engine.remix(product="starpio")

        assert mock_enqueue.call_count >= 1
        assert "remixed" in result
        assert result["remixed"] >= 1

    def test_no_top_pieces_returns_gracefully(self, mock_db, cfg):
        engine = RemixEngine(mock_db, cfg)
        mock_db.get_top_pieces.return_value = []

        result = engine.remix(product="starpio")

        assert result["remixed"] == 0

    def test_remix_uses_platform_aware_prompt(self, mock_db, cfg):
        engine = RemixEngine(mock_db, cfg)
        mock_db.get_top_pieces.return_value = [_viral_piece({"platform": "linkedin", "content": "Original LinkedIn post"})]

        prompts_seen = []
        def capture(**kwargs):
            prompts_seen.append(kwargs.get("messages", [{}])[0].get("content", ""))
            return MagicMock(content=[MagicMock(text="Remixed")])

        with patch("agents.viral.remix_engine.llm") as mock_llm, \
             patch("agents.viral.remix_engine.enqueue_content_task"):
            mock_llm.complete.side_effect = capture
            engine.remix(product="starpio")

        # Each remix call should name the target platform
        assert any("twitter" in p.lower() or "tiktok" in p.lower() for p in prompts_seen)


# ---------------------------------------------------------------------------
# TestGapFinder
# ---------------------------------------------------------------------------

class TestGapFinder:

    def test_gap_analysis_returns_10_topics(self, mock_db, cfg):
        finder = GapFinder(cfg)

        with patch("agents.viral.gap_finder.web_search") as mock_search, \
             patch("agents.viral.gap_finder.llm") as mock_llm:
            mock_search.return_value = [
                {"title": "Competitor post", "url": "grade.us/blog/reviews", "content": "review tips"}
            ]
            gap_json = json.dumps([
                {"topic": f"Gap topic {i}", "estimated_search_volume": 1000 - i * 50, "reason": "Underserved"}
                for i in range(10)
            ])
            mock_llm.complete.return_value.content = [MagicMock(text=gap_json)]

            result = finder.find_gaps(product="starpio")

        assert len(result["gaps"]) == 10

    def test_gap_topics_ranked_by_search_volume(self, mock_db, cfg):
        finder = GapFinder(cfg)

        with patch("agents.viral.gap_finder.web_search") as mock_search, \
             patch("agents.viral.gap_finder.llm") as mock_llm:
            mock_search.return_value = []
            gaps = [
                {"topic": f"Topic {i}", "estimated_search_volume": i * 100, "reason": "gap"}
                for i in range(10, 0, -1)
            ]
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(gaps))]

            result = finder.find_gaps(product="starpio")

        volumes = [g["estimated_search_volume"] for g in result["gaps"]]
        assert volumes == sorted(volumes, reverse=True)

    def test_top_3_enqueued_to_content_agent(self, mock_db, cfg):
        finder = GapFinder(cfg)

        with patch("agents.viral.gap_finder.web_search") as mock_search, \
             patch("agents.viral.gap_finder.llm") as mock_llm, \
             patch("agents.viral.gap_finder.enqueue_blog_post") as mock_enqueue:
            mock_search.return_value = []
            gaps = [
                {"topic": f"Gap {i}", "estimated_search_volume": 1000 - i * 100, "reason": "gap"}
                for i in range(10)
            ]
            mock_llm.complete.return_value.content = [MagicMock(text=json.dumps(gaps))]

            finder.find_gaps(product="starpio")

        assert mock_enqueue.call_count == 3

    def test_gap_finder_scrapes_competitor_blogs(self, mock_db, cfg):
        finder = GapFinder(cfg)

        with patch("agents.viral.gap_finder.web_search") as mock_search, \
             patch("agents.viral.gap_finder.llm") as mock_llm, \
             patch("agents.viral.gap_finder.enqueue_blog_post"):
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"topic": f"T{i}", "estimated_search_volume": 500, "reason": "gap"}
                    for i in range(10)
                ]))
            ]

            finder.find_gaps(product="starpio")

        # Should have searched for each competitor blog
        assert mock_search.call_count >= len(cfg["competitor_blogs"]["starpio"])

    def test_gap_each_topic_has_required_fields(self, mock_db, cfg):
        finder = GapFinder(cfg)

        with patch("agents.viral.gap_finder.web_search") as mock_search, \
             patch("agents.viral.gap_finder.llm") as mock_llm, \
             patch("agents.viral.gap_finder.enqueue_blog_post"):
            mock_search.return_value = []
            mock_llm.complete.return_value.content = [
                MagicMock(text=json.dumps([
                    {"topic": f"T{i}", "estimated_search_volume": 500, "reason": "gap"}
                    for i in range(10)
                ]))
            ]

            result = finder.find_gaps(product="starpio")

        for gap in result["gaps"]:
            assert "topic" in gap
            assert "estimated_search_volume" in gap
            assert "reason" in gap


# ---------------------------------------------------------------------------
# TestViralAgent — full dispatch
# ---------------------------------------------------------------------------

class TestViralAgent:

    def _make_agent(self):
        from agents.viral.main import ViralAgent
        config = MagicMock(spec=AgentConfig)
        config.custom = _cfg()
        config.llm_system_prompt = None
        return ViralAgent("viral", config)

    def test_unknown_action_returns_error(self):
        agent = self._make_agent()
        task = _task("not_a_real_action")
        result = agent.handle(task)
        assert result.success is False
        assert "error" in result.output

    def test_trend_monitor_dispatches(self):
        agent = self._make_agent()
        task = _task("trend_monitor", {"product": "starpio"})
        with patch.object(agent._scanner, "scan", return_value=[_trend()]) as mock_scan:
            result = agent.handle(task)
        mock_scan.assert_called_once()
        assert result.success is True

    def test_trend_monitor_all_products_when_no_product(self):
        agent = self._make_agent()
        task = _task("trend_monitor")
        with patch.object(agent._scanner, "scan_all", return_value={"scanned": 4}) as mock_scan_all:
            result = agent.handle(task)
        mock_scan_all.assert_called_once()
        assert result.success is True

    def test_create_viral_piece_dispatches(self):
        agent = self._make_agent()
        trend_id = str(uuid.uuid4())
        task = _task("create_viral_piece", {
            "trend_id": trend_id,
            "trend_topic": "Google reviews update",
            "product": "starpio",
            "platform": "twitter",
            "opportunity_window_hours": 6,
        })
        with patch.object(agent._creator, "create", return_value={"piece_id": "x", "hook": "H", "content": "C", "platform": "twitter", "format": "thread"}) as mock_create:
            result = agent.handle(task)
        mock_create.assert_called_once()
        assert result.success is True

    def test_hook_generator_dispatches(self):
        agent = self._make_agent()
        task = _task("hook_generator", {
            "topic": "review management",
            "platform": "linkedin",
            "tone": "educational",
        })
        with patch.object(agent._hooks, "generate", return_value={"hooks": []}) as mock_gen:
            result = agent.handle(task)
        mock_gen.assert_called_once()
        assert result.success is True

    def test_remix_winner_dispatches(self):
        agent = self._make_agent()
        task = _task("remix_winner", {"product": "starpio"})
        with patch.object(agent._remixer, "remix", return_value={"remixed": 3}) as mock_remix:
            result = agent.handle(task)
        mock_remix.assert_called_once()
        assert result.success is True

    def test_competitor_content_gap_dispatches(self):
        agent = self._make_agent()
        task = _task("competitor_content_gap", {"product": "starpio"})
        with patch.object(agent._gap_finder, "find_gaps", return_value={"gaps": []}) as mock_gaps:
            result = agent.handle(task)
        mock_gaps.assert_called_once()
        assert result.success is True

    def test_health_check_true_when_db_ok(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_recent_trends", return_value=[]):
            assert agent.health_check() is True

    def test_health_check_false_on_db_error(self):
        agent = self._make_agent()
        with patch.object(agent._db, "get_recent_trends", side_effect=Exception("db down")):
            assert agent.health_check() is False
