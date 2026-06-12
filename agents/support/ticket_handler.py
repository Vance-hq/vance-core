"""
Ticket handler — classify inbound support tickets and respond appropriately.

Classifications:
  BUG              → create GitHub issue, acknowledge with issue number
  BILLING          → pull Stripe subscription, answer factually
  HOW_TO           → search KB, generate response using KB as context
  FEATURE_REQUEST  → acknowledge, log, respond warmly
  COMPLAINT        → escalate to Dutch immediately + empathetic response
  UNSUBSCRIBE      → enqueue auto_resolve account_deletion
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from shared.llm.client import llm
from shared.logger import get_logger

from .db import SupportDB
from .mailer import send_email

logger = get_logger(__name__)

_VALID_CLASSIFICATIONS = {
    "BUG", "BILLING", "HOW_TO", "FEATURE_REQUEST", "COMPLAINT", "UNSUBSCRIBE",
}

_CLASSIFY_SYSTEM = """Classify this support ticket into exactly one category.

Valid categories:
  BUG              — app is broken or behaving incorrectly
  BILLING          — questions about charges, invoices, subscriptions
  HOW_TO           — how to use a feature; user needs guidance
  FEATURE_REQUEST  — asking for new functionality
  COMPLAINT        — expressing dissatisfaction, anger, or frustration
  UNSUBSCRIBE      — wants to cancel, delete account, or unsubscribe

Output ONLY the category name, nothing else.
"""

_DUTCH_VOICE = """You are Dutch, the founder of {product_name}.

Write as me — first person, direct, no bullshit. When I help someone I'm thorough
but I don't pad responses with filler. I own problems. I don't deflect. I keep it human.

Never promise a refund or credit without explicit confirmation. Never reveal internal pricing
strategy or system details. If you don't know something, say so — don't make it up.
"""


def enqueue_escalation(
    ticket_id: str,
    product: str,
    user_id: str,
    subject: str,
    body: str,
) -> None:
    """Push complaint to reporting agent for Dutch's immediate review."""
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="reporting",
            payload={
                "action": "escalate_complaint",
                "ticket_id": ticket_id,
                "product": product,
                "user_id": user_id,
                "subject": subject,
                "body": body,
            },
        )
    except Exception as exc:
        logger.warning("escalation_enqueue_failed", ticket_id=ticket_id, error=str(exc))


def enqueue_auto_resolve(
    action: str,
    user_id: str,
    user_email: str,
    product: str,
) -> None:
    """Push auto-resolution task back to support agent queue."""
    from shared.queue.queue import TaskQueue
    try:
        queue = TaskQueue()
        queue.push(
            agent="support",
            payload={
                "action": "resolve_auto",
                "auto_action": action,
                "user_id": user_id,
                "user_email": user_email,
                "product": product,
            },
        )
    except Exception as exc:
        logger.warning("auto_resolve_enqueue_failed", action=action, error=str(exc))


class TicketHandler:

    def __init__(self, db: SupportDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def handle(
        self,
        product: str,
        user_id: str,
        channel: str,
        subject: str,
        body: str,
        user_email: str,
    ) -> dict[str, Any]:
        classification = self._classify(subject, body)

        ticket_id = self._db.save_ticket(
            product=product,
            user_id=user_id,
            channel=channel,
            classification=classification,
            subject=subject,
            body=body,
        )

        result: dict[str, Any] = {
            "ticket_id": ticket_id,
            "classification": classification,
        }

        if classification == "BUG":
            issue_number, issue_url = self._create_github_issue(product, subject, body)
            result["github_issue"] = issue_number
            result["github_url"] = issue_url
            self._send_response(
                product=product,
                user_email=user_email,
                subject=f"Re: {subject}",
                body_text=(
                    f"I've logged this as GitHub issue #{issue_number}. "
                    f"You can track it here: {issue_url}. "
                    "I'll update you when it's resolved — typically within 24-48 hours."
                ),
            )

        elif classification == "BILLING":
            sub_data = self._fetch_stripe_subscription(user_id)
            response_text = self._generate_response(
                product=product,
                classification=classification,
                subject=subject,
                body=body,
                context=f"Stripe subscription data: {sub_data}",
            )
            self._send_response(product=product, user_email=user_email,
                                subject=f"Re: {subject}", body_text=response_text)

        elif classification == "HOW_TO":
            kb_articles = self._db.search_kb(product=product, query=f"{subject} {body}")
            context = "\n\n".join(
                f"Article: {a['title']}\n{a['body']}" for a in kb_articles[:2]
            ) if kb_articles else "No KB articles found for this topic."
            response_text = self._generate_response(
                product=product,
                classification=classification,
                subject=subject,
                body=body,
                context=context,
            )
            self._send_response(product=product, user_email=user_email,
                                subject=f"Re: {subject}", body_text=response_text)

        elif classification == "COMPLAINT":
            enqueue_escalation(
                ticket_id=ticket_id,
                product=product,
                user_id=user_id,
                subject=subject,
                body=body,
            )
            response_text = self._generate_response(
                product=product,
                classification=classification,
                subject=subject,
                body=body,
                context="",
            )
            self._send_response(product=product, user_email=user_email,
                                subject=f"Re: {subject}", body_text=response_text)

        elif classification == "UNSUBSCRIBE":
            enqueue_auto_resolve(
                action="account_deletion",
                user_id=user_id,
                user_email=user_email,
                product=product,
            )
            self._send_response(
                product=product,
                user_email=user_email,
                subject=f"Re: {subject}",
                body_text=(
                    "I've received your request and am processing your account deletion. "
                    "You'll receive a confirmation once it's complete. "
                    "All your data will be removed within 30 days per GDPR requirements."
                ),
            )

        else:
            # FEATURE_REQUEST and any fallback
            response_text = self._generate_response(
                product=product,
                classification=classification,
                subject=subject,
                body=body,
                context="",
            )
            self._send_response(product=product, user_email=user_email,
                                subject=f"Re: {subject}", body_text=response_text)

        logger.info(
            "ticket_handled",
            ticket_id=ticket_id,
            classification=classification,
            product=product,
        )
        return result

    # ------------------------------------------------------------------

    def _classify(self, subject: str, body: str) -> str:
        raw = llm.complete(
            messages=[{"role": "user", "content": f"Subject: {subject}\n\n{body}"}],
            system=_CLASSIFY_SYSTEM,
            max_tokens=20,
            metadata={"caller": "support.ticket_handler"},
        ).content[0].text.strip().upper()
        return raw if raw in _VALID_CLASSIFICATIONS else "HOW_TO"

    def _generate_response(
        self,
        product: str,
        classification: str,
        subject: str,
        body: str,
        context: str,
    ) -> str:
        product_name = self._cfg.get("products", {}).get(product, {}).get("name", product)
        system = _DUTCH_VOICE.format(product_name=product_name)
        prompt = (
            f"Support ticket ({classification})\n"
            f"Subject: {subject}\n"
            f"Message: {body}\n"
        )
        if context:
            prompt += f"\nContext:\n{context}\n"
        prompt += "\nWrite a helpful, direct response."
        return llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            max_tokens=400,
            metadata={"caller": "support.ticket_handler"},
        ).content[0].text.strip()

    def _create_github_issue(
        self,
        product: str,
        subject: str,
        body: str,
    ) -> tuple[int, str]:
        token = self._cfg.get("github_token", "")
        repo = self._cfg.get("github_repo", "")
        try:
            resp = httpx.post(
                f"https://api.github.com/repos/{repo}/issues",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "title": f"[{product.upper()}] {subject}",
                    "body": f"**Customer-reported bug**\n\n{body}",
                    "labels": ["bug", "customer-reported"],
                },
                timeout=15,
            )
            if resp.status_code == 201:
                data = resp.json()
                return data["number"], data["html_url"]
        except Exception as exc:
            logger.warning("github_issue_create_failed", error=str(exc))
        return 0, ""

    def _fetch_stripe_subscription(self, user_id: str) -> dict[str, Any]:
        api_key = self._cfg.get("stripe_api_key", "")
        try:
            resp = httpx.get(
                "https://api.stripe.com/v1/subscriptions",
                params={"customer": user_id, "limit": 1},
                auth=(api_key, ""),
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:
            logger.warning("stripe_fetch_failed", user_id=user_id, error=str(exc))
        return {}

    def _send_response(
        self,
        product: str,
        user_email: str,
        subject: str,
        body_text: str,
    ) -> None:
        prod_cfg = self._cfg.get("products", {}).get(product, {})
        html = body_text.replace("\n", "<br>")
        send_email(
            api_key=self._cfg.get("resend_api_key", ""),
            to=user_email,
            from_email=prod_cfg.get("support_email", "support@vance.com"),
            from_name=prod_cfg.get("from_name", "Support"),
            subject=subject,
            html=f"<p>{html}</p>",
        )
