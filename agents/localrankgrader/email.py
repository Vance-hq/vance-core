"""Transactional email sender for LocalRankGrader via Mailcow SMTP."""

from __future__ import annotations

import smtplib
import ssl
import uuid
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)

_OPEN_PIXEL_HTML = '<img src="{pixel_url}" width="1" height="1" alt="" style="display:none"/>'


class GraderMailer:
    """Send report and nurture emails for LocalRankGrader."""

    def send_report(
        self,
        to_email: str,
        to_name: str,
        business_name: str,
        score: int,
        lead_id: str,
        pdf_bytes: bytes,
        html_preview: str,
    ) -> str:
        subject = f"{business_name}'s Google Score: {score}/100 — Here's What's Holding You Back"
        pixel = self._pixel_url(lead_id, step=1)
        body_html = html_preview + _OPEN_PIXEL_HTML.format(pixel_url=pixel)
        message_id = self._build_message_id()
        self._smtp_send(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_html=body_html,
            body_text=f"Your GBP score: {score}/100. See the attached PDF for details.",
            message_id=message_id,
            attachments=[("GBP_Audit_Report.pdf", pdf_bytes, "application/pdf")],
        )
        logger.info("grader_report_sent", to=to_email, score=score, business=business_name)
        return message_id

    def send_nurture(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body_html: str,
        body_text: str,
        lead_id: str,
        step: int,
    ) -> str:
        pixel = self._pixel_url(lead_id, step=step)
        body_html_with_pixel = body_html + _OPEN_PIXEL_HTML.format(pixel_url=pixel)
        message_id = self._build_message_id()
        self._smtp_send(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            body_html=body_html_with_pixel,
            body_text=body_text,
            message_id=message_id,
        )
        logger.info("grader_nurture_sent", to=to_email, step=step)
        return message_id

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _smtp_send(
        self,
        to_email: str,
        to_name: str,
        subject: str,
        body_html: str,
        body_text: str,
        message_id: str,
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> None:
        msg = MIMEMultipart("mixed" if attachments else "alternative")
        msg["Subject"] = subject
        msg["From"] = f"LocalRankGrader <{settings.MAILCOW_SMTP_USER}>"
        msg["To"] = f"{to_name} <{to_email}>"
        msg["Message-ID"] = message_id

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(body_text, "plain", "utf-8"))
        alt.attach(MIMEText(body_html, "html", "utf-8"))
        msg.attach(alt)

        if attachments:
            for filename, data, mime_type in attachments:
                part = MIMEApplication(data, Name=filename)
                part["Content-Disposition"] = f'attachment; filename="{filename}"'
                msg.attach(part)

        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.MAILCOW_HOST, settings.MAILCOW_SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.login(settings.MAILCOW_SMTP_USER, settings.MAILCOW_SMTP_PASSWORD)
            smtp.sendmail(settings.MAILCOW_SMTP_USER, to_email, msg.as_string())

    def _pixel_url(self, lead_id: str, step: int) -> str:
        base = settings.GRADER_TRACKER_URL.rstrip("/")
        return f"{base}/hooks/grader/open/{lead_id}/{step}.gif"

    def _build_message_id(self) -> str:
        domain = settings.MAILCOW_DOMAIN or "localrankgrader.com"
        return f"<{uuid.uuid4()}@{domain}>"
