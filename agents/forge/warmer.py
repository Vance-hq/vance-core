"""
Domain warm-up manager.

Schedule (configurable via config.yaml warm_up_schedule_daily):
  Week 1: 10/day  |  Week 2: 25/day  |  Week 3: 50/day  |  Week 4+: 100/day

Deliverability check: IMAP login to seed accounts → check spam folder hit rate.
If spam rate > 5%: reduce volume, emit ALERT event.
"""

from __future__ import annotations

import imaplib
import smtplib
import ssl
import time
import uuid
from typing import Any

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)

_WARMUP_SUBJECT = "Quick check-in"
_WARMUP_TEXT = (
    "Hey,\n\nJust checking in — hope all is well on your end. "
    "Let me know if you want to catch up sometime.\n\nBest,"
)


class DomainWarmer:
    # warm-up limits by week (0-indexed)
    _DEFAULT_SCHEDULE = [10, 25, 50, 100]

    def __init__(self, schedule: list[int] | None = None) -> None:
        self._schedule = schedule or self._DEFAULT_SCHEDULE

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def warm(self, alias: str, alias_password: str, days_warmed: int) -> dict[str, Any]:
        """
        Send the day's warm-up batch and check deliverability.
        Returns metrics dict.
        """
        daily_limit = self.get_daily_limit(days_warmed)
        seed_list = self._load_seed_list()
        if not seed_list:
            return {"status": "no_seed_list", "alias": alias}

        sent = self._send_warmup_batch(alias, alias_password, seed_list, daily_limit)
        spam_rate = self._check_deliverability(seed_list)

        result: dict[str, Any] = {
            "alias": alias,
            "days_warmed": days_warmed,
            "daily_limit": daily_limit,
            "sent": sent,
            "spam_rate": spam_rate,
        }

        if spam_rate > 0.05:
            result["alert"] = True
            result["action"] = "reduce_volume"
            logger.error(
                "warmup_spam_rate_high",
                alias=alias,
                spam_rate=round(spam_rate, 3),
                recommendation="reduce_send_volume",
            )
        else:
            result["alert"] = False
            logger.info("warmup_batch_complete", alias=alias, sent=sent, spam_rate=round(spam_rate, 3))

        return result

    def get_daily_limit(self, days_warmed: int) -> int:
        """Return daily send limit based on number of days the domain has been warmed."""
        week = days_warmed // 7
        idx = min(week, len(self._schedule) - 1)
        return self._schedule[idx]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send_warmup_batch(
        self,
        alias: str,
        alias_password: str,
        seed_list: list[dict[str, str]],
        limit: int,
    ) -> int:
        sent = 0
        ctx = ssl.create_default_context()
        to_send = seed_list[:limit]

        try:
            with smtplib.SMTP(settings.MAILCOW_HOST, settings.MAILCOW_SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.login(alias, alias_password)

                for seed in to_send:
                    try:
                        self._send_one(server, alias, seed["email"], seed.get("name", ""))
                        sent += 1
                        time.sleep(0.5)  # brief gap between sends
                    except Exception as exc:
                        logger.debug("warmup_send_failed", to=seed["email"], error=str(exc))
        except Exception as exc:
            logger.warning("warmup_smtp_failed", alias=alias, error=str(exc))

        return sent

    def _send_one(
        self,
        server: smtplib.SMTP,
        from_email: str,
        to_email: str,
        to_name: str,
    ) -> None:
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart("alternative")
        msg["Subject"] = _WARMUP_SUBJECT
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Message-ID"] = f"<warmup-{uuid.uuid4()}@{settings.MAILCOW_DOMAIN}>"

        greeting = f"Hey {to_name}," if to_name else "Hey,"
        body = _WARMUP_TEXT.replace("Hey,", greeting)
        msg.attach(MIMEText(body, "plain", "utf-8"))
        server.sendmail(from_email, to_email, msg.as_string())

    def _check_deliverability(self, seed_list: list[dict[str, str]]) -> float:
        """
        Log into each seed account via IMAP and check if the last warmup email
        landed in Spam. Returns fraction landing in spam.
        """
        spam_count = 0
        checked = 0

        for seed in seed_list:
            imap_host = seed.get("imap_host")
            imap_user = seed.get("email")
            imap_pass = seed.get("password")

            if not (imap_host and imap_user and imap_pass):
                continue

            try:
                with imaplib.IMAP4_SSL(imap_host, timeout=10) as mail:
                    mail.login(imap_user, imap_pass)
                    # Check common spam folder names
                    for folder in ("Spam", "Junk", "[Gmail]/Spam", "INBOX.Spam"):
                        status, _ = mail.select(folder, readonly=True)
                        if status != "OK":
                            continue
                        _, data = mail.search(None, 'SUBJECT "Quick check-in"')
                        if data and data[0]:
                            spam_count += 1
                        break
                checked += 1
            except Exception as exc:
                logger.debug("imap_check_failed", seed=imap_user, error=str(exc))

        if checked == 0:
            return 0.0
        return spam_count / checked

    def _load_seed_list(self) -> list[dict[str, str]]:
        """Load seed accounts from settings. Format: JSON array of {email, password, imap_host, name}."""
        import json
        raw = settings.FORGE_SEED_LIST
        if not raw:
            logger.warning("forge_seed_list_empty")
            return []
        try:
            return json.loads(raw)
        except Exception as exc:
            logger.warning("forge_seed_list_parse_failed", error=str(exc))
            return []
