"""
Sales email sender — Mailcow SMTP, Dutch's voice.

Thin wrapper around smtplib shared across all sales email types.
Each calling module supplies the LLM-generated subject + body.
"""

from __future__ import annotations

import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)

DUTCH_VOICE = """You are Dutch — a 26-year trades veteran who built and sold two SaaS businesses.

Voice rules (non-negotiable):
- Peer-to-peer tone. Never talk down, never be sycophantic.
- NEVER use: "I hope this finds you well", "circle back", "synergy", "touch base",
  "reaching out", "just following up", "leverage", "pain points".
- Write like a contractor who figured out software — direct, specific, zero fluff.
- Max 4 sentences per email unless the context demands more. One clear ask at the end.
- No bullet lists unless listing specific items. No markdown in the email body.
- Sign off as: Dutch"""


class SalesMailer:

    def send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body_text: str,
        from_email: str,
        from_name: str,
        from_password: str,
    ) -> str:
        """Send email. Returns Message-ID."""
        message_id = f"<{uuid.uuid4()}@{settings.MAILCOW_DOMAIN}>"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
        msg["Message-ID"] = message_id
        msg["List-Unsubscribe"] = f"<mailto:{from_email}?subject=Unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        html_body = "<p>" + body_text.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.MAILCOW_HOST, settings.MAILCOW_SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(from_email, from_password)
            server.sendmail(from_email, to_email, msg.as_string())

        logger.info("sales_email_sent", to=to_email, subject=subject, message_id=message_id)
        return message_id
