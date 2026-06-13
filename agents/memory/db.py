"""Memory DB — agent_memories (pgvector), decision_log, and preferences tables."""

from __future__ import annotations

from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class MemoryDB:

    def store(
        self,
        context_key: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
        expires_at: str | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if embedding:
                    cur.execute(
                        """
                        INSERT INTO agent_memories (context_key, content, embedding, metadata, expires_at)
                        VALUES (%s, %s, %s::vector, %s, %s) RETURNING id
                        """,
                        (context_key, content, str(embedding), psycopg2.extras.Json(metadata or {}), expires_at),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO agent_memories (context_key, content, metadata, expires_at)
                        VALUES (%s, %s, %s, %s) RETURNING id
                        """,
                        (context_key, content, psycopg2.extras.Json(metadata or {}), expires_at),
                    )
                return str(cur.fetchone()["id"])

    def search_similar(self, context_key: str, embedding: list[float], limit: int = 5) -> list[dict[str, Any]]:
        """Cosine similarity search over stored embeddings."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, context_key, content, metadata, created_at,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM agent_memories
                    WHERE context_key = %s
                      AND embedding IS NOT NULL
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (str(embedding), context_key, str(embedding), limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def list_recent(self, context_key: str, limit: int = 20) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, context_key, content, metadata, created_at
                    FROM agent_memories
                    WHERE context_key = %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (context_key, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def delete_expired(self) -> int:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM agent_memories WHERE expires_at IS NOT NULL AND expires_at <= NOW()")
                return cur.rowcount

    def delete_by_pattern(self, context_key: str, pattern: str) -> int:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM agent_memories WHERE context_key = %s AND content ILIKE %s",
                    (context_key, f"%{pattern}%"),
                )
                return cur.rowcount

    def summarize_and_compact(self, context_key: str, keep_recent: int = 5) -> list[dict[str, Any]]:
        """Return memories older than the most recent N for compaction."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, content FROM agent_memories
                    WHERE context_key = %s
                      AND (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY created_at DESC
                    OFFSET %s
                    """,
                    (context_key, keep_recent),
                )
                return [dict(r) for r in cur.fetchall()]

    def delete_by_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM agent_memories WHERE id = ANY(%s::uuid[])",
                    (ids,),
                )

    # ------------------------------------------------------------------
    # decision_log (migration 025)
    # ------------------------------------------------------------------

    def save_decision(
        self,
        agent: str,
        action: str,
        intent: str,
        outcome: str,
        product: str = "",
        embedding: list[float] | None = None,
    ) -> str:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if embedding:
                    cur.execute(
                        """
                        INSERT INTO decision_log (agent, action, intent, outcome, product, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s::vector) RETURNING id
                        """,
                        (agent, action, intent, outcome, product, str(embedding)),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO decision_log (agent, action, intent, outcome, product)
                        VALUES (%s, %s, %s, %s, %s) RETURNING id
                        """,
                        (agent, action, intent, outcome, product),
                    )
                return str(cur.fetchone()["id"])

    def list_recent_decisions(
        self, days: int = 7, product: str = "", limit: int = 20
    ) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if product:
                    cur.execute(
                        """
                        SELECT id, agent, action, intent, outcome, product, timestamp
                        FROM decision_log
                        WHERE timestamp >= NOW() - INTERVAL '%s days'
                          AND product = %s
                        ORDER BY timestamp DESC LIMIT %s
                        """,
                        (days, product, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, agent, action, intent, outcome, product, timestamp
                        FROM decision_log
                        WHERE timestamp >= NOW() - INTERVAL '%s days'
                        ORDER BY timestamp DESC LIMIT %s
                        """,
                        (days, limit),
                    )
                return [dict(r) for r in cur.fetchall()]

    def search_decisions(
        self, embedding: list[float], product: str = "", limit: int = 5
    ) -> list[dict[str, Any]]:
        """Cosine similarity search over decision embeddings."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if product:
                    cur.execute(
                        """
                        SELECT id, agent, action, intent, outcome, product, timestamp,
                               1 - (embedding <=> %s::vector) AS similarity
                        FROM decision_log
                        WHERE embedding IS NOT NULL AND product = %s
                        ORDER BY embedding <=> %s::vector LIMIT %s
                        """,
                        (str(embedding), product, str(embedding), limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, agent, action, intent, outcome, product, timestamp,
                               1 - (embedding <=> %s::vector) AS similarity
                        FROM decision_log
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> %s::vector LIMIT %s
                        """,
                        (str(embedding), str(embedding), limit),
                    )
                return [dict(r) for r in cur.fetchall()]

    def delete_decisions_by_topic(self, topic: str) -> int:
        """GDPR-safe deletion: remove decisions where intent or outcome mentions topic."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM decision_log WHERE intent ILIKE %s OR outcome ILIKE %s",
                    (f"%{topic}%", f"%{topic}%"),
                )
                return cur.rowcount

    def delete_decisions_by_product(self, product: str) -> int:
        """Remove all decisions for a specific product."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM decision_log WHERE product = %s", (product,))
                return cur.rowcount

    # ------------------------------------------------------------------
    # preferences (migration 025)
    # ------------------------------------------------------------------

    def upsert_preference(
        self,
        key: str,
        value: str,
        confidence: float = 0.5,
        source_evidence: str = "",
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO preferences (key, value, confidence, source_evidence)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        value           = EXCLUDED.value,
                        confidence      = EXCLUDED.confidence,
                        source_evidence = EXCLUDED.source_evidence,
                        learned_at      = NOW()
                    """,
                    (key, value, confidence, source_evidence),
                )

    def list_preferences(self, min_confidence: float = 0.0) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM preferences WHERE confidence >= %s ORDER BY confidence DESC",
                    (min_confidence,),
                )
                return [dict(r) for r in cur.fetchall()]
