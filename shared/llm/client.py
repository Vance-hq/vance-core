"""
Single Anthropic API wrapper for the entire Vance system.
No agent or module may import anthropic directly — use this client.
Also exposes web_search() backed by SearXNG with DuckDuckGo HTML fallback.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote_plus

import anthropic
import httpx

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    """Thread-safe Anthropic client with retry/backoff and structured logging."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> anthropic.types.Message:
        """Send a completion request with automatic retry on transient errors."""
        resolved_model = model or settings.ANTHROPIC_DEFAULT_MODEL
        resolved_max_tokens = max_tokens or settings.ANTHROPIC_MAX_TOKENS

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": resolved_max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        last_exc: Exception | None = None
        for attempt in range(1, settings.ANTHROPIC_MAX_RETRIES + 1):
            try:
                logger.debug(
                    "llm_request",
                    model=resolved_model,
                    attempt=attempt,
                    caller=metadata.get("caller") if metadata else None,
                )
                response = self._client.messages.create(**kwargs)
                logger.debug(
                    "llm_response",
                    model=resolved_model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
                return response
            except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
                last_exc = exc
                if attempt < settings.ANTHROPIC_MAX_RETRIES:
                    delay = settings.ANTHROPIC_RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
                    logger.warning("llm_retry", attempt=attempt, delay=delay, error=str(exc))
                    time.sleep(delay)

        raise RuntimeError(
            f"LLM request failed after {settings.ANTHROPIC_MAX_RETRIES} attempts"
        ) from last_exc

    def stream(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ):
        """Streaming variant — yields text deltas."""
        resolved_model = model or settings.ANTHROPIC_DEFAULT_MODEL
        resolved_max_tokens = max_tokens or settings.ANTHROPIC_MAX_TOKENS

        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "max_tokens": resolved_max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        with self._client.messages.stream(**kwargs) as stream:
            yield from stream.text_stream


# Module-level singleton — import and use directly
llm = LLMClient()


class _WebSearchClient:
    """SearXNG-backed web search with DuckDuckGo HTML fallback.

    Returns a list of {"title", "url", "content"} dicts.
    Falls back to DuckDuckGo HTML scrape when SearXNG returns < 3 results.
    """

    _headers = {"User-Agent": "Mozilla/5.0 (compatible; Vance/1.0; +https://vance.ai)"}

    def __call__(self, query: str, num_results: int = 10) -> list[dict[str, str]]:
        results = self._searxng(query, num_results)
        if len(results) < 3:
            logger.debug("searxng_insufficient_results", count=len(results), fallback="ddg")
            results = self._ddg(query, num_results)
        return results

    def _searxng(self, query: str, num_results: int) -> list[dict[str, str]]:
        try:
            resp = httpx.get(
                f"{settings.SEARXNG_URL}/search",
                params={"q": query, "format": "json", "pageno": 1},
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            raw = resp.json().get("results", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                }
                for r in raw[:num_results]
            ]
        except Exception as exc:
            logger.warning("searxng_search_failed", error=str(exc))
            return []

    def _ddg(self, query: str, num_results: int) -> list[dict[str, str]]:
        try:
            resp = httpx.get(
                f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
                headers=self._headers,
                timeout=10,
                follow_redirects=True,
            )
            resp.raise_for_status()
            html = resp.text
            urls_titles = re.findall(
                r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)<',
                html,
            )
            snippets = re.findall(r'class="result__snippet"[^>]*>([^<]+)<', html)
            return [
                {
                    "title": title.strip(),
                    "url": href,
                    "content": snippets[i].strip() if i < len(snippets) else "",
                }
                for i, (href, title) in enumerate(urls_titles[:num_results])
            ]
        except Exception as exc:
            logger.warning("ddg_fallback_failed", error=str(exc))
            return []


# Module-level search function — import and call directly
web_search = _WebSearchClient()
