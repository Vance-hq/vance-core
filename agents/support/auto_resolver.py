"""
Auto-resolver — handle common support actions without human intervention.

Actions:
  password_reset       — trigger Supabase auth reset email
  plan_change          — update Stripe subscription to new price
  account_deletion     — GDPR-compliant: cancel Stripe, delete Supabase user
  subscription_pause   — pause Stripe subscription collection
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from shared.logger import get_logger

from .db import SupportDB

logger = get_logger(__name__)


class AutoResolver:

    def __init__(self, db: SupportDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def resolve(
        self,
        action: str,
        user_id: str,
        user_email: str,
        product: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        handlers = {
            "password_reset": self._password_reset,
            "plan_change": self._plan_change,
            "account_deletion": self._account_deletion,
            "subscription_pause": self._subscription_pause,
        }
        handler = handlers.get(action)
        if not handler:
            return {"action": action, "success": False, "error": f"Unknown auto-resolve action: {action}"}

        try:
            outcome = handler(user_id=user_id, user_email=user_email, product=product, **kwargs)
            # Log to support_tickets for audit trail
            self._db.save_ticket(
                product=product,
                user_id=user_id,
                channel="auto",
                classification="AUTO_RESOLVE",
                subject=f"auto_resolve:{action}",
                body=f"Automatically resolved: {action}",
                status="resolved",
                auto_resolved=True,
            )
            logger.info("auto_resolved", action=action, user_id=user_id, product=product)
            return {"action": action, "success": True, **outcome}
        except Exception as exc:
            logger.warning("auto_resolve_failed", action=action, user_id=user_id, error=str(exc))
            return {"action": action, "success": False, "error": str(exc)}

    # ------------------------------------------------------------------

    def _password_reset(
        self,
        user_id: str,
        user_email: str,
        product: str,
        **_: Any,
    ) -> dict[str, Any]:
        supabase_url = self._cfg.get("supabase_url", "")
        service_key = self._cfg.get("supabase_service_key", "")
        resp = httpx.post(
            f"{supabase_url}/auth/v1/admin/users/{user_id}/reset-password",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "application/json",
            },
            json={"email": user_email},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Supabase reset failed: {resp.status_code}")
        return {"email": user_email}

    def _plan_change(
        self,
        user_id: str,
        user_email: str,
        product: str,
        new_plan_id: str = "",
        **_: Any,
    ) -> dict[str, Any]:
        api_key = self._cfg.get("stripe_api_key", "")
        # Fetch current subscription
        resp = httpx.get(
            "https://api.stripe.com/v1/subscriptions",
            params={"customer": user_id, "limit": 1},
            auth=(api_key, ""),
            timeout=15,
        )
        subs = resp.json().get("data", [])
        if not subs:
            raise RuntimeError("No active subscription found")
        sub_id = subs[0]["id"]

        # Update to new price
        resp = httpx.post(
            f"https://api.stripe.com/v1/subscriptions/{sub_id}",
            auth=(api_key, ""),
            data={"items[0][price]": new_plan_id},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Stripe plan change failed: {resp.status_code}")
        return {"subscription_id": sub_id, "new_plan_id": new_plan_id}

    def _account_deletion(
        self,
        user_id: str,
        user_email: str,
        product: str,
        **_: Any,
    ) -> dict[str, Any]:
        api_key = self._cfg.get("stripe_api_key", "")
        supabase_url = self._cfg.get("supabase_url", "")
        service_key = self._cfg.get("supabase_service_key", "")

        # Cancel Stripe subscriptions
        resp = httpx.get(
            "https://api.stripe.com/v1/subscriptions",
            params={"customer": user_id, "status": "active"},
            auth=(api_key, ""),
            timeout=15,
        )
        for sub in resp.json().get("data", []):
            httpx.delete(
                f"https://api.stripe.com/v1/subscriptions/{sub['id']}",
                auth=(api_key, ""),
                timeout=15,
            )

        # Delete Supabase auth user
        del_resp = httpx.delete(
            f"{supabase_url}/auth/v1/admin/users/{user_id}",
            headers={
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
            timeout=15,
        )
        if del_resp.status_code not in (200, 204):
            raise RuntimeError(f"Supabase delete failed: {del_resp.status_code}")

        return {"deleted_at": datetime.now(timezone.utc).isoformat()}

    def _subscription_pause(
        self,
        user_id: str,
        user_email: str,
        product: str,
        **_: Any,
    ) -> dict[str, Any]:
        api_key = self._cfg.get("stripe_api_key", "")
        resp = httpx.get(
            "https://api.stripe.com/v1/subscriptions",
            params={"customer": user_id, "limit": 1},
            auth=(api_key, ""),
            timeout=15,
        )
        subs = resp.json().get("data", [])
        if not subs:
            raise RuntimeError("No active subscription found")
        sub_id = subs[0]["id"]

        pause_resp = httpx.post(
            f"https://api.stripe.com/v1/subscriptions/{sub_id}",
            auth=(api_key, ""),
            data={"pause_collection[behavior]": "void"},
            timeout=15,
        )
        if pause_resp.status_code != 200:
            raise RuntimeError(f"Stripe pause failed: {pause_resp.status_code}")
        return {"subscription_id": sub_id, "paused": True}
