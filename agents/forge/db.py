"""Direct Postgres operations on forge_* tables via shared/db/client.py."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class ForgeDB:
    # ------------------------------------------------------------------
    # Leads
    # ------------------------------------------------------------------

    def upsert_lead(self, lead: dict[str, Any]) -> str:
        """Insert or update a lead by email. Returns lead id."""
        lid = str(uuid.uuid4())
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO forge_leads
                        (id, product, email, first_name, last_name, company,
                         title, city, phone, website, source, research_notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET
                        first_name     = EXCLUDED.first_name,
                        last_name      = EXCLUDED.last_name,
                        company        = EXCLUDED.company,
                        title          = EXCLUDED.title,
                        city           = EXCLUDED.city,
                        phone          = COALESCE(EXCLUDED.phone, forge_leads.phone),
                        website        = COALESCE(EXCLUDED.website, forge_leads.website),
                        research_notes = COALESCE(EXCLUDED.research_notes, forge_leads.research_notes),
                        updated_at     = now()
                    RETURNING id
                    """,
                    (
                        lid,
                        lead.get("product"),
                        lead.get("email"),
                        lead.get("first_name"),
                        lead.get("last_name"),
                        lead.get("company"),
                        lead.get("title"),
                        lead.get("city"),
                        lead.get("phone"),
                        lead.get("website"),
                        lead.get("source"),
                        lead.get("research_notes"),
                    ),
                )
                row = cur.fetchone()
                return str(row[0]) if row else lid

    def lead_exists(self, email: str) -> bool:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM forge_leads WHERE email = %s LIMIT 1", (email,))
                return cur.fetchone() is not None

    def get_lead(self, lead_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM forge_leads WHERE id = %s", (lead_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_leads_by_list(self, lead_ids: list[str]) -> list[dict[str, Any]]:
        if not lead_ids:
            return []
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM forge_leads WHERE id = ANY(%s) AND status NOT IN ('UNSUBSCRIBED','BOUNCED')",
                    (lead_ids,),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_leads_by_product(self, product: str, status: str = "NEW", limit: int = 500) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM forge_leads WHERE product = %s AND status = %s ORDER BY created_at DESC LIMIT %s",
                    (product, status, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def update_lead_status(self, lead_id: str, status: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE forge_leads SET status = %s, updated_at = now() WHERE id = %s",
                    (status, lead_id),
                )

    def update_lead_score(self, lead_id: str, score: int) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE forge_leads SET score = %s, updated_at = now() WHERE id = %s",
                    (score, lead_id),
                )

    def update_lead_crm_id(self, lead_id: str, crm_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE forge_leads SET crm_id = %s, updated_at = now() WHERE id = %s",
                    (crm_id, lead_id),
                )

    def count_leads_by_status(self, status: str) -> int:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM forge_leads WHERE status = %s", (status,))
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def get_leads_above_score(self, threshold: int) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM forge_leads WHERE score >= %s AND status NOT IN ('HOT','CONVERTED','UNSUBSCRIBED','BOUNCED')",
                    (threshold,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Sequences
    # ------------------------------------------------------------------

    def get_sequence(self, sequence_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM forge_sequences WHERE id = %s", (sequence_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_active_sequences(self) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM forge_sequences WHERE status = 'ACTIVE'")
                return [dict(r) for r in cur.fetchall()]

    def update_sequence_status(self, sequence_id: str, status: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE forge_sequences SET status = %s, updated_at = now() WHERE id = %s",
                    (status, sequence_id),
                )

    def apply_sequence_variant(self, sequence_id: str, variant: dict[str, Any]) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE forge_sequences SET active_variant = %s, updated_at = now() WHERE id = %s",
                    (psycopg2.extras.Json(variant), sequence_id),
                )

    # ------------------------------------------------------------------
    # Sends
    # ------------------------------------------------------------------

    def log_send(
        self,
        lead_id: str,
        sequence_id: str,
        step_number: int,
        subject: str,
        from_alias: str,
        message_id: str,
    ) -> str:
        sid = str(uuid.uuid4())
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO forge_sends
                        (id, lead_id, sequence_id, step_number, subject, from_alias, message_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'SENT')
                    """,
                    (sid, lead_id, sequence_id, step_number, subject, from_alias, message_id),
                )
        return sid

    def update_send_status(self, send_id: str, status: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE forge_sends SET status = %s WHERE id = %s",
                    (status, send_id),
                )

    def get_sends_for_sequence(self, sequence_id: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM forge_sends WHERE sequence_id = %s ORDER BY sent_at",
                    (sequence_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_sends_for_lead(self, lead_id: str, sequence_id: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM forge_sends WHERE lead_id = %s AND sequence_id = %s ORDER BY step_number",
                    (lead_id, sequence_id),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_send_by_message_id(self, message_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM forge_sends WHERE message_id = %s", (message_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    # ------------------------------------------------------------------
    # Opens
    # ------------------------------------------------------------------

    def log_open(self, send_id: str, ip_address: str | None = None) -> str:
        oid = str(uuid.uuid4())
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO forge_opens (id, send_id, ip_address) VALUES (%s, %s, %s)",
                    (oid, send_id, ip_address),
                )
        return oid

    def get_open_count(self, send_id: str) -> int:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM forge_opens WHERE send_id = %s", (send_id,))
                row = cur.fetchone()
                return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Replies
    # ------------------------------------------------------------------

    def log_reply(self, send_id: str, reply_type: str, reply_body: str) -> str:
        rid = str(uuid.uuid4())
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO forge_replies (id, send_id, reply_type, reply_body) VALUES (%s, %s, %s, %s)",
                    (rid, send_id, reply_type, reply_body),
                )
        return rid

    def get_replies_for_sequence(self, sequence_id: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT r.* FROM forge_replies r
                    JOIN forge_sends s ON r.send_id = s.id
                    WHERE s.sequence_id = %s
                    ORDER BY r.received_at DESC
                    """,
                    (sequence_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # A/B Tests
    # ------------------------------------------------------------------

    def create_ab_test(
        self,
        sequence_id: str,
        variant_a: dict[str, Any],
        variant_b: dict[str, Any],
        metric: str,
    ) -> str:
        tid = str(uuid.uuid4())
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO forge_ab_tests (id, sequence_id, variant_a, variant_b, metric)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        tid,
                        sequence_id,
                        psycopg2.extras.Json(variant_a),
                        psycopg2.extras.Json(variant_b),
                        metric,
                    ),
                )
        return tid

    def resolve_ab_test(
        self,
        test_id: str,
        winner: str,
        confidence: float,
        analysis: str,
    ) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE forge_ab_tests
                    SET winner = %s, confidence = %s, analysis = %s, resolved_at = now()
                    WHERE id = %s
                    """,
                    (winner, confidence, analysis, test_id),
                )

    def get_open_ab_tests(self, sequence_id: str) -> list[dict[str, Any]]:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM forge_ab_tests WHERE sequence_id = %s AND winner IS NULL",
                    (sequence_id,),
                )
                return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Aggregate metrics
    # ------------------------------------------------------------------

    def get_sequence_metrics(self, sequence_id: str) -> dict[str, Any]:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT s.id)                          AS sends,
                        COUNT(DISTINCT o.id)                          AS opens,
                        COUNT(DISTINCT r.id) FILTER (WHERE r.reply_type = 'INTERESTED')  AS interested,
                        COUNT(DISTINCT r.id) FILTER (WHERE r.reply_type = 'UNSUBSCRIBE') AS unsubscribes,
                        COUNT(DISTINCT s.id) FILTER (WHERE s.status   = 'BOUNCED')       AS bounces
                    FROM forge_sends s
                    LEFT JOIN forge_opens  o ON o.send_id = s.id
                    LEFT JOIN forge_replies r ON r.send_id = s.id
                    WHERE s.sequence_id = %s
                    """,
                    (sequence_id,),
                )
                row = cur.fetchone()
                if not row:
                    return {"sends": 0, "opens": 0, "interested": 0, "unsubscribes": 0, "bounces": 0}
                sends, opens, interested, unsubs, bounces = row
                return {
                    "sends": sends or 0,
                    "opens": opens or 0,
                    "interested": interested or 0,
                    "unsubscribes": unsubs or 0,
                    "bounces": bounces or 0,
                    "open_rate": round((opens or 0) / sends, 3) if sends else 0.0,
                    "reply_rate": round((interested or 0) / sends, 3) if sends else 0.0,
                    "bounce_rate": round((bounces or 0) / sends, 3) if sends else 0.0,
                }

    def get_daily_metrics(self, day: str) -> dict[str, Any]:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT s.id)    AS sends,
                        COUNT(DISTINCT o.id)    AS opens,
                        COUNT(DISTINCT r.id)    AS replies,
                        COUNT(DISTINCT s.id) FILTER (WHERE s.status = 'BOUNCED') AS bounces
                    FROM forge_sends s
                    LEFT JOIN forge_opens   o ON o.send_id = s.id
                    LEFT JOIN forge_replies r ON r.send_id = s.id
                    WHERE DATE(s.sent_at) = %s::date
                    """,
                    (day,),
                )
                row = cur.fetchone()
                if not row:
                    return {"sends": 0, "opens": 0, "replies": 0, "bounces": 0}
                sends, opens, replies, bounces = row
                return {
                    "sends": sends or 0,
                    "opens": opens or 0,
                    "replies": replies or 0,
                    "bounces": bounces or 0,
                }

    def get_lead_engagement(self, lead_id: str) -> dict[str, Any]:
        """Raw engagement counts for scoring."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(DISTINCT s.id)  AS sends,
                        COUNT(DISTINCT o.id)  AS opens,
                        COUNT(DISTINCT r.id) FILTER (WHERE r.reply_type = 'INTERESTED') AS replies,
                        COUNT(DISTINCT r.id) FILTER (WHERE r.reply_type = 'UNSUBSCRIBE') AS unsubscribes
                    FROM forge_sends s
                    LEFT JOIN forge_opens   o ON o.send_id = s.id
                    LEFT JOIN forge_replies r ON r.send_id = s.id
                    WHERE s.lead_id = %s
                    """,
                    (lead_id,),
                )
                row = cur.fetchone()
                if not row:
                    return {"sends": 0, "opens": 0, "replies": 0, "unsubscribes": 0}
                sends, opens, replies, unsubs = row
                return {
                    "sends": sends or 0,
                    "opens": opens or 0,
                    "replies": replies or 0,
                    "unsubscribes": unsubs or 0,
                }
