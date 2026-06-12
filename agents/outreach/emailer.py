"""
Follow-up email sender — Mailcow SMTP.

Generates a reply via LLM matching Dutch's voice, then sends via Mailcow.
The system prompt is the canonical Dutch voice definition from config.

Thread-safe: uses a new SMTP connection per send (no shared state).
"""

from __future__ import annotations

import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from shared.config.settings import settings
from shared.llm.client import llm
from shared.logger import get_logger

logger = get_logger(__name__)

_REPLY_SYSTEM = """You are Dutch — a 26-year trades veteran who built and sold two SaaS businesses.

Voice rules (non-negotiable):
- Peer-to-peer tone. Never talk down, never be sycophantic.
- NEVER use: "I hope this finds you well", "circle back", "synergy", "touch base",
  "reaching out", "just following up", "leverage", "pain points".
- Write like a contractor who figured out software — direct, specific, zero fluff.
- Max 4 sentences per email. One clear ask at the end.
- Match the energy of their reply: if they're brief, be brief.

You are writing a reply email. Output the plain-text body only — no subject line, no sign-off
(those are added separately). Do not add markdown formatting.
"""

_SUBJECT_SYSTEM = "Reply with a concise email subject line only — no quotes, no explanation, max 8 words."


class FollowupMailer:

    def send_followup(
        self,
        contact: dict[str, Any],
        original_email: str,
        their_reply: str,
        from_email: str,
        from_name: str,
        from_password: str,
        product: str,
    ) -> dict[str, Any]:
        """
        Generate + send a personalised reply.

        Args:
            contact:        row from contacts table
            original_email: the email we originally sent
            their_reply:    the text of their inbound reply
            from_email:     Mailcow alias to send from
            from_name:      display name
            from_password:  Mailcow alias password
            product:        product context string
        """
        to_email = contact.get("email", "")
        to_name = contact.get("name", "")
        company = contact.get("company", "")

        prompt = (
            f"Contact: {to_name} at {company}\n"
            f"Product context: {product}\n\n"
            f"Our original email:\n{original_email}\n\n"
            f"Their reply:\n{their_reply}\n\n"
            "Write the reply email body."
        )

        body_text = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_REPLY_SYSTEM,
            max_tokens=200,
            metadata={"caller": "outreach.emailer"},
        ).content[0].text.strip()

        subject_prompt = f"Original subject: Re: [previous thread]\nReply body:\n{body_text}"
        subject = llm.complete(
            messages=[{"role": "user", "content": subject_prompt}],
            system=_SUBJECT_SYSTEM,
            max_tokens=20,
            metadata={"caller": "outreach.emailer.subject"},
        ).content[0].text.strip().lstrip("Subject: ")

        subject = f"Re: {subject}" if not subject.startswith("Re:") else subject

        message_id = f"<{uuid.uuid4()}@{settings.MAILCOW_DOMAIN}>"

        self._send(
            from_email=from_email,
            from_password=from_password,
            from_name=from_name,
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_text=body_text,
            message_id=message_id,
        )

        logger.info("followup_sent", to=to_email, product=product, message_id=message_id)
        return {
            "sent": True,
            "to": to_email,
            "subject": subject,
            "body_preview": body_text[:120],
            "message_id": message_id,
        }

    # ------------------------------------------------------------------

    def _send(
        self,
        from_email: str,
        from_password: str,
        from_name: str,
        to_email: str,
        to_name: str,
        subject: str,
        body_text: str,
        message_id: str,
    ) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
        msg["Message-ID"] = message_id
        msg["List-Unsubscribe"] = f"<mailto:{from_email}?subject=Unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        html_body = body_text.replace("\n", "<br>")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(f"<p>{html_body}</p>", "html", "utf-8"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.MAILCOW_HOST, settings.MAILCOW_SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(from_email, from_password)
            server.sendmail(from_email, to_email, msg.as_string())
