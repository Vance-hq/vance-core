"""
Email sequence launcher — Mailcow SMTP, per-alias throttle, LLM personalization.

Throttle limits (configurable via config.yaml):
  - 40 emails/hour per alias   (warm-up safe)
  - 200 emails/day  per alias

Tracking pixel injected as 1x1 PNG: {FORGE_PIXEL_SERVER_URL}/p/{send_id}.gif
"""

from __future__ import annotations

import json
import smtplib
import ssl
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING, Any

import redis

from shared.config.settings import settings
from shared.llm.client import llm
from shared.logger import get_logger

if TYPE_CHECKING:
    from .db import ForgeDB

logger = get_logger(__name__)

_PIXEL_HTML = '<img src="{pixel_url}" width="1" height="1" alt="" style="display:none"/>'

_HOOK_PROMPT = """
You are a cold email personalization expert. Given the research brief below, write ONE
specific, concrete hook sentence (max 20 words) that opens a cold email to this prospect.

The hook must:
- Reference something specific about their business (not generic)
- Create a natural transition into the value prop
- Sound like it was written by a human who did their research
- NOT mention AI, automation software, or our product name

Research brief:
{research_notes}

Business: {company} | Role: {title} | City: {city}

Output ONLY the hook sentence. No quotes, no explanation.
""".strip()


class SequenceLauncher:
    def __init__(self, db: "ForgeDB", config: dict[str, Any]) -> None:
        self._db = db
        self._hourly_limit: int = config.get("hourly_send_limit", 40)
        self._daily_limit: int = config.get("daily_send_limit", 200)
        self._redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB_QUEUE,
            decode_responses=True,
        )
        self._sender_pool: list[dict[str, str]] = self._load_sender_pool()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def launch(self, lead_list_id: str, sequence_id: str, from_alias: str) -> dict[str, Any]:
        """Enroll all leads in the sequence and send step 1 immediately."""
        sequence = self._db.get_sequence(sequence_id)
        if not sequence:
            raise ValueError(f"Sequence not found: {sequence_id}")
        if sequence["status"] not in ("ACTIVE", "DRAFT"):
            raise ValueError(f"Sequence not launchable (status={sequence['status']})")

        steps: list[dict[str, Any]] = sequence.get("steps") or []
        if not steps:
            raise ValueError("Sequence has no steps")

        step_one = steps[0]
        sender = self._find_sender(from_alias)
        if not sender:
            raise ValueError(f"Alias not in sender pool: {from_alias}")

        lead_ids: list[str] = json.loads(lead_list_id) if lead_list_id.startswith("[") else [lead_list_id]
        leads = self._db.get_leads_by_list(lead_ids)

        sent, throttled, failed = 0, 0, 0
        for lead in leads:
            if not self._can_send(from_alias):
                throttled += 1
                continue
            try:
                self._send_step(lead, step_one, sequence_id, sender)
                self._record_throttle(from_alias)
                sent += 1
            except Exception as exc:
                logger.warning("sequence_send_failed", lead_id=str(lead["id"]), error=str(exc))
                failed += 1

        self._db.update_sequence_status(sequence_id, "ACTIVE")
        logger.info("sequence_launched", sequence_id=sequence_id, sent=sent, throttled=throttled, failed=failed)
        return {"sent": sent, "throttled": throttled, "failed": failed}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send_step(
        self,
        lead: dict[str, Any],
        step: dict[str, Any],
        sequence_id: str,
        sender: dict[str, str],
    ) -> str:
        hook = self._generate_hook(lead)
        subject = self._personalize(step.get("subject", ""), lead, hook)
        body_html = self._personalize(step.get("body_html", ""), lead, hook)
        body_text = self._personalize(step.get("body_text", ""), lead, hook)

        # Apply active_variant overrides if present
        sequence = self._db.get_sequence(sequence_id)
        if sequence and sequence.get("active_variant"):
            av = sequence["active_variant"]
            if av.get("field") == "subject":
                subject = av["value"]

        message_id = f"<{uuid.uuid4()}@{settings.MAILCOW_DOMAIN}>"

        send_id = self._db.log_send(
            lead_id=str(lead["id"]),
            sequence_id=sequence_id,
            step_number=step.get("step", 1),
            subject=subject,
            from_alias=sender["email"],
            message_id=message_id,
        )

        # Inject tracking pixel
        pixel_url = f"{settings.FORGE_PIXEL_SERVER_URL}/p/{send_id}.gif"
        body_html_tracked = body_html + _PIXEL_HTML.format(pixel_url=pixel_url)

        self._smtp_send(
            from_email=sender["email"],
            from_password=sender["password"],
            from_name=sender.get("display_name", sender["email"]),
            to_email=str(lead["email"]),
            subject=subject,
            html=body_html_tracked,
            text=body_text,
            message_id=message_id,
        )
        self._db.update_lead_status(str(lead["id"]), "CONTACTED")
        return send_id

    def _generate_hook(self, lead: dict[str, Any]) -> str:
        research = lead.get("research_notes") or ""
        if not research:
            return ""
        try:
            prompt = _HOOK_PROMPT.format(
                research_notes=research[:800],
                company=lead.get("company", ""),
                title=lead.get("title", ""),
                city=lead.get("city", ""),
            )
            return llm.complete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=60,
                metadata={"caller": "forge.sequence.hook"},
            ).content[0].text.strip()
        except Exception as exc:
            logger.debug("hook_generation_failed", error=str(exc))
            return ""

    def _personalize(self, template: str, lead: dict[str, Any], hook: str) -> str:
        replacements = {
            "{first_name}": lead.get("first_name") or "there",
            "{last_name}": lead.get("last_name") or "",
            "{business_name}": lead.get("company") or "",
            "{city}": lead.get("city") or "",
            "{title}": lead.get("title") or "",
            "{pain_point}": lead.get("research_notes") or "",
            "{specific_hook}": hook,
        }
        for key, value in replacements.items():
            template = template.replace(key, str(value))
        return template

    def _smtp_send(
        self,
        from_email: str,
        from_password: str,
        from_name: str,
        to_email: str,
        subject: str,
        html: str,
        text: str,
        message_id: str,
    ) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = to_email
        msg["Message-ID"] = message_id
        msg["List-Unsubscribe"] = f"<mailto:{from_email}?subject=Unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.MAILCOW_HOST, settings.MAILCOW_SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(from_email, from_password)
            server.sendmail(from_email, to_email, msg.as_string())

    def _can_send(self, alias: str) -> bool:
        hourly = int(self._redis.get(f"forge:throttle:{alias}:hourly") or 0)
        daily = int(self._redis.get(f"forge:throttle:{alias}:daily") or 0)
        return hourly < self._hourly_limit and daily < self._daily_limit

    def _record_throttle(self, alias: str) -> None:
        pipe = self._redis.pipeline()
        pipe.incr(f"forge:throttle:{alias}:hourly")
        pipe.expire(f"forge:throttle:{alias}:hourly", 3600)
        pipe.incr(f"forge:throttle:{alias}:daily")
        pipe.expire(f"forge:throttle:{alias}:daily", 86400)
        pipe.execute()

    def _load_sender_pool(self) -> list[dict[str, str]]:
        raw = settings.FORGE_SENDER_POOL
        if not raw:
            return []
        try:
            return json.loads(raw)
        except Exception:
            return []

    def _find_sender(self, alias: str) -> dict[str, str] | None:
        for sender in self._sender_pool:
            if sender.get("email") == alias:
                return sender
        return None
