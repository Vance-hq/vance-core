"""DB helpers for the outreach agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class OutreachDB:

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    def upsert_contact(self, data: dict[str, Any]) -> str:
        """Insert or update a contact. Returns contact UUID."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO contacts (id, email, linkedin_url, name, company, role, product)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET
                        linkedin_url    = COALESCE(EXCLUDED.linkedin_url, contacts.linkedin_url),
                        name            = COALESCE(EXCLUDED.name, contacts.name),
                        company         = COALESCE(EXCLUDED.company, contacts.company),
                        role            = COALESCE(EXCLUDED.role, contacts.role),
                        updated_at      = now()
                    RETURNING id
                    """,
                    (
                        str(uuid.uuid4()),
                        data.get("email"),
                        data.get("linkedin_url"),
                        data.get("name"),
                        data.get("company"),
                        data.get("role"),
                        data["product"],
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return str(row[0])

    def get_contact(self, contact_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM contacts WHERE id = %s", (contact_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_contact_by_email(self, email: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM contacts WHERE email = %s", (email,))
                row = cur.fetchone()
                return dict(row) if row else None

    def update_contact_score(self, contact_id: str, score: int, tier: str, next_action: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE contacts
                    SET score = %s, tier = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (score, tier, contact_id),
                )
                conn.commit()

    def update_research_notes(self, contact_id: str, notes: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE contacts SET research_notes = %s, updated_at = now() WHERE id = %s",
                    (notes, contact_id),
                )
                conn.commit()

    def mark_unsubscribed(self, contact_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE contacts SET unsubscribed_at = now(), updated_at = now() WHERE id = %s",
                    (contact_id,),
                )
                conn.commit()

    def is_unsubscribed(self, contact_id: str) -> bool:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT unsubscribed_at FROM contacts WHERE id = %s", (contact_id,))
                row = cur.fetchone()
                return bool(row and row[0])

    # ------------------------------------------------------------------
    # LinkedIn outreach
    # ------------------------------------------------------------------

    def log_linkedin_action(
        self,
        contact_id: str,
        action_type: str,
        content_sent: str,
    ) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                row_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO linkedin_outreach (id, contact_id, action_type, content_sent)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (row_id, contact_id, action_type, content_sent),
                )
                conn.commit()
                return row_id

    def record_linkedin_response(self, outreach_id: str, response: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE linkedin_outreach SET response = %s, responded_at = now() WHERE id = %s",
                    (response, outreach_id),
                )
                conn.commit()

    def hours_since_last_linkedin_message(self, contact_id: str) -> float:
        """Returns hours elapsed since the most recent message sent to this contact."""
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXTRACT(EPOCH FROM (now() - sent_at)) / 3600
                    FROM linkedin_outreach
                    WHERE contact_id = %s AND action_type = 'message'
                    ORDER BY sent_at DESC
                    LIMIT 1
                    """,
                    (contact_id,),
                )
                row = cur.fetchone()
                return float(row[0]) if row else float("inf")

    def linkedin_connect_sent(self, contact_id: str) -> bool:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM linkedin_outreach WHERE contact_id = %s AND action_type = 'connect' LIMIT 1",
                    (contact_id,),
                )
                return cur.fetchone() is not None

    # ------------------------------------------------------------------
    # Outreach sequences
    # ------------------------------------------------------------------

    def get_sequence(self, contact_id: str) -> dict[str, Any] | None:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM outreach_sequences WHERE contact_id = %s", (contact_id,))
                row = cur.fetchone()
                return dict(row) if row else None

    def upsert_sequence(self, contact_id: str, product: str) -> str:
        with get_db() as conn:
            with conn.cursor() as cur:
                seq_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO outreach_sequences (id, contact_id, product)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (contact_id) DO UPDATE SET
                        status     = CASE WHEN outreach_sequences.status = 'OPTED_OUT' THEN 'OPTED_OUT'
                                         ELSE 'ACTIVE' END,
                        updated_at = now()
                    RETURNING id
                    """,
                    (seq_id, contact_id, product),
                )
                row = cur.fetchone()
                conn.commit()
                return str(row[0])

    def advance_sequence(self, contact_id: str, next_step: int, next_action_at: datetime) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE outreach_sequences
                    SET current_step = %s, next_action_at = %s, updated_at = now()
                    WHERE contact_id = %s
                    """,
                    (next_step, next_action_at, contact_id),
                )
                conn.commit()

    def complete_sequence(self, contact_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE outreach_sequences SET status = 'COMPLETE', updated_at = now() WHERE contact_id = %s",
                    (contact_id,),
                )
                conn.commit()

    def opt_out_sequence(self, contact_id: str) -> None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE outreach_sequences SET status = 'OPTED_OUT', updated_at = now() WHERE contact_id = %s",
                    (contact_id,),
                )
                conn.commit()

    def due_sequences(self) -> list[dict[str, Any]]:
        """Return all active sequences whose next_action_at is now or past."""
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT s.*, c.email, c.linkedin_url, c.name, c.company, c.role, c.research_notes
                    FROM outreach_sequences s
                    JOIN contacts c ON c.id = s.contact_id
                    WHERE s.status = 'ACTIVE' AND s.next_action_at <= now()
                    ORDER BY s.next_action_at
                    LIMIT 100
                    """,
                )
                return [dict(r) for r in cur.fetchall()]
