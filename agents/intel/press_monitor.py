"""Press monitoring — SerpAPI news search for product/founder/competitor mentions."""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)


def _search_news(keyword: str, api_key: str, num: int = 10) -> list[dict[str, Any]]:
    """SerpAPI Google News search for a keyword."""
    import httpx

    try:
        resp = httpx.get(
            "https://serpapi.com/search",
            params={"q": keyword, "tbm": "nws", "num": num, "api_key": api_key},
            timeout=15,
        )
        data = resp.json()
        return data.get("news_results", [])
    except Exception as exc:
        logger.warning("news_search_failed", keyword=keyword, error=str(exc))
        return []


class PressMonitor:

    def __init__(self, db: Any, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        keywords = prod_cfg.get("press_keywords", [])
        api_key = self._cfg.get("serp_api_key", "")

        mentions_stored = 0
        routed_positive = 0
        routed_negative = 0

        for keyword in keywords:
            articles = _search_news(keyword, api_key)
            for article in articles:
                headline = article.get("title", "")
                source = article.get("source", "")
                url = article.get("link", "")
                snippet = article.get("snippet", "")

                if not headline or not url:
                    continue

                sentiment = self._classify_sentiment(headline, snippet)
                mention_id = self._db.save_press_mention(
                    keyword=keyword,
                    headline=headline,
                    source=source,
                    url=url,
                    snippet=snippet,
                    sentiment=sentiment,
                    routed_to="content" if sentiment == "positive" else ("strategy" if sentiment == "negative" else ""),
                )

                if mention_id is None:
                    continue  # duplicate

                mentions_stored += 1

                if sentiment == "positive":
                    self._route_to_content(headline, snippet, url, product)
                    routed_positive += 1
                elif sentiment == "negative":
                    self._route_to_strategy(headline, snippet, url, product)
                    routed_negative += 1

        return {
            "product": product,
            "keywords_checked": len(keywords),
            "mentions_stored": mentions_stored,
            "routed_positive": routed_positive,
            "routed_negative": routed_negative,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_sentiment(self, headline: str, snippet: str) -> str:
        try:
            resp = llm.complete(
                messages=[{"role": "user", "content": f"Headline: {headline}\nSnippet: {snippet}"}],
                system=(
                    "Classify the sentiment of this press mention for a SaaS brand. "
                    'Reply with exactly one word: "positive", "negative", or "neutral".'
                ),
                max_tokens=10,
            )
            word = resp.content[0].text.strip().lower().split()[0]
            if word in {"positive", "negative", "neutral"}:
                return word
        except Exception:
            pass
        return "neutral"

    def _route_to_content(self, headline: str, snippet: str, url: str, product: str) -> None:
        try:
            TaskQueue().push(
                "content",
                {
                    "action": "press_mention_positive",
                    "product": product,
                    "headline": headline,
                    "snippet": snippet,
                    "url": url,
                },
            )
        except Exception as exc:
            logger.warning("press_route_content_failed", error=str(exc))

    def _route_to_strategy(self, headline: str, snippet: str, url: str, product: str) -> None:
        try:
            TaskQueue().push(
                "strategy",
                {
                    "action": "market_signal",
                    "product": product,
                    "signal_type": "negative_press",
                    "summary": f"Negative press: {headline}",
                    "source_url": url,
                },
            )
        except Exception as exc:
            logger.warning("press_route_strategy_failed", error=str(exc))
