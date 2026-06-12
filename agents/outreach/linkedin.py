"""
LinkedIn browser automation via Playwright.

Login state is persisted to LINKEDIN_STATE_FILE (mounted volume) so cookies
survive container restarts. On first run it logs in with credentials; subsequent
runs reuse the saved state.

Rate limits enforced here:
  - connect requests: max 20/day (LinkedIn soft-limits ~100/week)
  - messages: 48-hour throttle enforced via DB (OutreachDB.hours_since_last_linkedin_message)
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

import redis

from shared.config.settings import settings
from shared.logger import get_logger

logger = get_logger(__name__)

LINKEDIN_STATE_FILE = os.environ.get("LINKEDIN_STATE_FILE", "/app/logs/linkedin_state.json")
_CONNECT_DAILY_KEY = "outreach:linkedin:connect_count"
_CONNECT_DAILY_LIMIT = 20


class LinkedInClient:

    def __init__(self) -> None:
        # Lazy Playwright import — not installed on every image
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        self._sync_playwright = sync_playwright
        self._redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB_QUEUE,
            decode_responses=True,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send_connection_request(self, profile_url: str, note: str) -> dict[str, Any]:
        """Send a LinkedIn connection request with a personalised note."""
        if not self._can_connect_today():
            return {"sent": False, "reason": "daily_connect_limit_reached"}

        with self._sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = self._load_context(browser)
            page = ctx.new_page()
            try:
                page.goto(profile_url, wait_until="domcontentloaded", timeout=30_000)
                self._human_pause(2, 4)

                # Find the Connect button (may be inside "More" dropdown)
                connect_btn = page.locator("button:has-text('Connect')").first
                if not connect_btn.is_visible():
                    more_btn = page.locator("button:has-text('More')").first
                    if more_btn.is_visible():
                        more_btn.click()
                        self._human_pause(0.5, 1.2)
                        connect_btn = page.locator("div[role='menu'] >> text=Connect").first

                if not connect_btn.is_visible():
                    return {"sent": False, "reason": "connect_button_not_found"}

                connect_btn.click()
                self._human_pause(1, 2)

                # "Add a note" option in modal
                add_note_btn = page.locator("button:has-text('Add a note')").first
                if add_note_btn.is_visible():
                    add_note_btn.click()
                    self._human_pause(0.5, 1)
                    page.locator("textarea[name='message']").fill(note[:280])
                    self._human_pause(0.5, 1.5)

                page.locator("button:has-text('Send')").first.click()
                self._human_pause(1, 2)

                self._record_connect_today()
                self._save_context(ctx)
                logger.info("linkedin_connect_sent", profile_url=profile_url)
                return {"sent": True, "note": note}

            except Exception as exc:
                logger.error("linkedin_connect_failed", error=str(exc), profile_url=profile_url)
                return {"sent": False, "reason": str(exc)}
            finally:
                browser.close()

    def send_direct_message(self, linkedin_id: str, message: str) -> dict[str, Any]:
        """Send a DM to an existing first-degree connection."""
        with self._sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = self._load_context(browser)
            page = ctx.new_page()
            try:
                # Open messaging overlay via new-message URL
                page.goto(
                    f"https://www.linkedin.com/messaging/thread/new/?recipient={linkedin_id}",
                    wait_until="domcontentloaded",
                    timeout=30_000,
                )
                self._human_pause(2, 4)

                msg_box = page.locator("div[role='textbox']").first
                if not msg_box.is_visible():
                    return {"sent": False, "reason": "message_box_not_found"}

                msg_box.click()
                # Type with realistic cadence
                for char in message:
                    msg_box.type(char, delay=random.randint(30, 90))
                self._human_pause(0.5, 1.5)

                page.keyboard.press("Enter")
                self._human_pause(1, 2)

                self._save_context(ctx)
                logger.info("linkedin_message_sent", linkedin_id=linkedin_id)
                return {"sent": True}

            except Exception as exc:
                logger.error("linkedin_message_failed", error=str(exc), linkedin_id=linkedin_id)
                return {"sent": False, "reason": str(exc)}
            finally:
                browser.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_context(self, browser: Any) -> Any:
        if os.path.exists(LINKEDIN_STATE_FILE):
            ctx = browser.new_context(storage_state=LINKEDIN_STATE_FILE)
            logger.debug("linkedin_context_loaded", state_file=LINKEDIN_STATE_FILE)
            return ctx

        ctx = browser.new_context()
        page = ctx.new_page()
        self._login(page)
        ctx.storage_state(path=LINKEDIN_STATE_FILE)
        return ctx

    def _login(self, page: Any) -> None:
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30_000)
        self._human_pause(1, 2)
        page.locator("#username").fill(settings.LINKEDIN_EMAIL)
        self._human_pause(0.3, 0.8)
        page.locator("#password").fill(settings.LINKEDIN_PASSWORD)
        self._human_pause(0.5, 1)
        page.locator("button[type='submit']").click()
        page.wait_for_url("**/feed/**", timeout=15_000)
        logger.info("linkedin_logged_in")

    def _save_context(self, ctx: Any) -> None:
        ctx.storage_state(path=LINKEDIN_STATE_FILE)

    def _can_connect_today(self) -> bool:
        count = int(self._redis.get(_CONNECT_DAILY_KEY) or 0)
        return count < _CONNECT_DAILY_LIMIT

    def _record_connect_today(self) -> None:
        pipe = self._redis.pipeline()
        pipe.incr(_CONNECT_DAILY_KEY)
        pipe.expire(_CONNECT_DAILY_KEY, 86_400)
        pipe.execute()

    @staticmethod
    def _human_pause(lo: float, hi: float) -> None:
        time.sleep(random.uniform(lo, hi))
