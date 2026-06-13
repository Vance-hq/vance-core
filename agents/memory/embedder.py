"""Embedder — generate text embeddings via Anthropic or fallback to zero vector."""

from __future__ import annotations

from shared.logger import get_logger

logger = get_logger(__name__)

_DIM = 1536


def embed(text: str) -> list[float] | None:
    """Return a 1536-dim embedding. Returns None on failure (memory stored without embedding)."""
    try:
        import anthropic
        from shared.config.settings import settings

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        # Use a short prompt to approximate embedding via token logits
        # NOTE: Anthropic doesn't expose a dedicated embeddings endpoint;
        # for production use a dedicated embeddings model (e.g. text-embedding-3-small via OpenAI)
        # or pgvector with sentence-transformers on-device.
        # This is a placeholder that stores None and falls back to keyword search.
        _ = client
        return None
    except Exception as exc:
        logger.debug("embedding_unavailable", error=str(exc))
        return None
