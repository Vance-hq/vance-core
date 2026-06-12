"""Shared secret authentication for all webhook endpoints."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from shared.config.settings import settings


async def verify_hook_secret(x_vance_hook_secret: str = Header(default="")) -> None:
    """Dependency — raises 401 if the shared secret is missing or wrong.

    Uses constant-time comparison to prevent timing attacks.
    Returns no detail on failure to avoid leaking why it failed.
    """
    expected = settings.VANCE_HOOK_SECRET
    if not expected or not hmac.compare_digest(x_vance_hook_secret, expected):
        raise HTTPException(status_code=401)
