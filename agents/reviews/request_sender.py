"""
Review request sender — SMS + email to customers 24 hours after job completion.

Personalised with tech name, job type, and address (first line only).
Tracks sent requests in review_requests table to prevent duplicates.
"""

from __future__ import annotations

import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from agents.integrations.connectors.twilio import TwilioConnector
from shared.config.settings import settings
from shared.logger import get_logger

from .db import ReviewsDB

logger = get_logger(__name__)

# Review links per platform — set via config or env
_REVIEW_LINKS: dict[str, dict[str, str]] = {
    "trusted_plumbing": {
        "google": "",
        "yelp": "",
        "facebook": "",
    },
}

_SMS_TEMPLATE = (
    "Hi {first_name}, it's Dutch from Trusted Plumbing — {tech_name} just wrapped up "
    "your {job_type} at {address}. If we did right by you, a quick Google review helps "
    "us a lot: {review_link}. Takes 30 seconds. — Dutch"
)

_EMAIL_SUBJECT = "How'd we do on your {job_type}?"

_EMAIL_BODY = """\
Hi {first_name},

{tech_name} finished your {job_type} at {address} today.

If everything went well, I'd appreciate a quick review — it's the main way new customers \
find us:

{review_link}

And if anything wasn't right, just reply to this email directly. I read every one.

— Dutch Munn, Trusted Plumbing
"""


class ReviewRequestSender:

    def __init__(self, db: ReviewsDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._from_email = cfg.get("from_email", "")
        self._from_name = cfg.get("from_name", "Dutch Munn")
        self._from_password = cfg.get("from_password", "")

    def send(
        self,
        job_id: str,
        business: str,
        contact_id: str | None,
        phone: str | None,
        email: str | None,
        first_name: str,
        tech_name: str,
        job_type: str,
        address: str,
    ) -> dict[str, Any]:
        if self._db.review_request_sent(job_id, business):
            return {"skipped": True, "reason": "already_sent"}

        review_link = _REVIEW_LINKS.get(business, {}).get("google", "")

        sms_sent = False
        email_sent = False

        if phone:
            sms_sent = self._send_sms(
                phone=phone,
                first_name=first_name,
                tech_name=tech_name,
                job_type=job_type,
                address=address,
                review_link=review_link,
            )

        if email and self._from_email:
            email_sent = self._send_email(
                to_email=email,
                first_name=first_name,
                tech_name=tech_name,
                job_type=job_type,
                address=address,
                review_link=review_link,
            )

        self._db.log_review_request(
            job_id=job_id,
            business=business,
            contact_id=contact_id,
            phone=phone,
            email=email,
        )

        logger.info(
            "review_request_sent",
            job_id=job_id,
            business=business,
            sms_sent=sms_sent,
            email_sent=email_sent,
        )
        return {"sent": True, "sms_sent": sms_sent, "email_sent": email_sent}

    # ------------------------------------------------------------------

    def _send_sms(
        self,
        phone: str,
        first_name: str,
        tech_name: str,
        job_type: str,
        address: str,
        review_link: str,
    ) -> bool:
        body = _SMS_TEMPLATE.format(
            first_name=first_name,
            tech_name=tech_name,
            job_type=job_type,
            address=address,
            review_link=review_link or "https://g.page/r/trusted-plumbing-review",
        )
        try:
            twilio = TwilioConnector(called_by="reviews", method_name="send_sms")
            twilio.send_sms(to=phone, body=body)
            return True
        except Exception as exc:
            logger.error("review_request_sms_failed", phone=phone, error=str(exc))
            return False

    def _send_email(
        self,
        to_email: str,
        first_name: str,
        tech_name: str,
        job_type: str,
        address: str,
        review_link: str,
    ) -> bool:
        subject = _EMAIL_SUBJECT.format(job_type=job_type)
        body = _EMAIL_BODY.format(
            first_name=first_name,
            tech_name=tech_name,
            job_type=job_type,
            address=address,
            review_link=review_link or "https://g.page/r/trusted-plumbing-review",
        )

        message_id = f"<{uuid.uuid4()}@{settings.MAILCOW_DOMAIN}>"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self._from_name} <{self._from_email}>"
        msg["To"] = to_email
        msg["Message-ID"] = message_id
        msg.attach(MIMEText(body, "plain"))

        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(settings.MAILCOW_HOST, settings.MAILCOW_SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.login(self._from_email, self._from_password)
                smtp.sendmail(self._from_email, [to_email], msg.as_string())
            return True
        except Exception as exc:
            logger.error("review_request_email_failed", to=to_email, error=str(exc))
            return False
