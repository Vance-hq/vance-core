"""Mailcow inbound reply handler.

Payload shape (sent by Mailcow Sieve filter via HTTP action):
{
    "from_email":           "lead@example.com",
    "to_email":             "outreach@yourdomain.com",
    "subject":              "Re: Quick question",
    "body":                 "...",
    "original_message_id":  "<uuid@mail.yourdomain.com>"   # In-Reply-To header
}
"""

from __future__ import annotations

import json
import re
from typing import Any

import psycopg2.extras

from shared.db import get_db
from shared.llm.client import llm
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)

# Priority values matching orchestrator routing_config
_PRIORITY_HIGH = 3
_PRIORITY_NORMAL = 5

# Keywords that unambiguously signal an unsubscribe — no LLM needed
_UNSUB_PATTERNS = re.compile(
    r"\b(unsubscribe|opt.?out|remove me|stop emailing|take me off|don.?t (email|contact)|"
    r"no (more|thanks)|please remove)\b",
    re.IGNORECASE,
)

_queue = TaskQueue()


def handle_mailcow_reply(payload: dict[str, Any]) -> dict[str, Any]:
    from_email = payload.get("from_email", "").strip().lower()
    to_email = payload.get("to_email", "").strip().lower()
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    original_message_id = payload.get("original_message_id", "")

    logger.info("mailcow_reply_received", from_email=from_email, original_message_id=original_message_id)

    # ------------------------------------------------------------------
    # 1. Look up original send for campaign context
    # ------------------------------------------------------------------
    send_id: str | None = None
    campaign_context: dict[str, Any] = {}

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if original_message_id:
                cur.execute(
                    "SELECT id, campaign_id, campaign_name, contact_id, contact_email "
                    "FROM campaign_sends WHERE message_id = %s",
                    (original_message_id,),
                )
                row = cur.fetchone()
                if row:
                    send_id = str(row["id"])
                    campaign_context = dict(row)

    # ------------------------------------------------------------------
    # 2. Classify — keyword shortcut for UNSUBSCRIBE, LLM for everything else
    # ------------------------------------------------------------------
    search_text = f"{subject} {body}"
    if _UNSUB_PATTERNS.search(search_text):
        category = "UNSUBSCRIBE"
        confidence = 1.0
        classified_by = "keyword"
    else:
        category, confidence = _classify_with_llm(subject, body)
        classified_by = "llm"

    logger.info(
        "reply_classified",
        from_email=from_email,
        category=category,
        confidence=confidence,
        method=classified_by,
    )

    # ------------------------------------------------------------------
    # 3. Act on classification
    # ------------------------------------------------------------------
    task_id: str | None = None

    if category == "UNSUBSCRIBE":
        _mark_unsubscribed(from_email)

    elif category in ("INTERESTED", "QUESTION"):
        task_id = _queue.push(
            agent="outreach",
            payload={
                "action": "score_lead",
                "from_email": from_email,
                "subject": subject,
                "body": body,
                "reply_category": category,
                "campaign_context": campaign_context,
                "original_message_id": original_message_id,
            },
            priority=_PRIORITY_HIGH,
        )
        logger.info("outreach_task_enqueued", task_id=task_id, category=category)

    # ------------------------------------------------------------------
    # 4. Persist classification log
    # ------------------------------------------------------------------
    _log_classification(
        reply_message_id=payload.get("message_id", ""),
        original_message_id=original_message_id,
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        category=category,
        confidence=confidence,
        classified_by=classified_by,
        task_id=task_id,
        send_id=send_id,
    )

    return {"status": "ok", "category": category, "task_id": task_id}


def _classify_with_llm(subject: str, body: str) -> tuple[str, float]:
    """Ask Claude to classify the reply. Returns (category, confidence)."""
    prompt = (
        "Classify this inbound email reply from a sales outreach campaign.\n\n"
        f"Subject: {subject}\n"
        f"Body: {body[:1500]}\n\n"
        "Return JSON only — no explanation, no markdown:\n"
        '{"category": "INTERESTED|NOT_INTERESTED|OUT_OF_OFFICE|QUESTION", "confidence": 0.0}'
    )
    raw = llm.complete(
        messages=[{"role": "user", "content": prompt}],
        system=(
            "You are an email classification assistant. "
            "Respond with a single JSON object only. No explanation."
        ),
        max_tokens=64,
        metadata={"caller": "mailcow_reply"},
    )
    text = raw.content[0].text.strip()

    # Strip accidental markdown fences
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)

    try:
        result = json.loads(text)
        category = result.get("category", "NOT_INTERESTED").upper()
        confidence = float(result.get("confidence", 0.5))
        valid = {"INTERESTED", "NOT_INTERESTED", "OUT_OF_OFFICE", "QUESTION"}
        if category not in valid:
            category = "NOT_INTERESTED"
            confidence = 0.5
    except (json.JSONDecodeError, ValueError):
        logger.warning("llm_classification_parse_error", raw=text)
        category = "NOT_INTERESTED"
        confidence = 0.0

    return category, confidence


def _mark_unsubscribed(email: str) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO contacts (email, unsubscribed, unsubscribed_at)
                VALUES (%s, TRUE, now())
                ON CONFLICT (email) DO UPDATE
                    SET unsubscribed = TRUE,
                        unsubscribed_at = EXCLUDED.unsubscribed_at,
                        updated_at = now()
                """,
                (email,),
            )
    logger.info("contact_unsubscribed", email=email)


def _log_classification(
    *,
    reply_message_id: str,
    original_message_id: str,
    from_email: str,
    to_email: str,
    subject: str,
    category: str,
    confidence: float,
    classified_by: str,
    task_id: str | None,
    send_id: str | None,
) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reply_classifications
                    (reply_message_id, original_message_id, from_email, to_email,
                     subject, category, confidence, classified_by, task_id, send_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    reply_message_id or None,
                    original_message_id or None,
                    from_email,
                    to_email,
                    subject or None,
                    category,
                    confidence,
                    classified_by,
                    task_id,
                    send_id,
                ),
            )
