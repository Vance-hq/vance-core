"""Shared Google OAuth2 access-token helper (refresh token → cached Bearer token)."""
from __future__ import annotations

import httpx
import redis

from shared.config.settings import settings

_TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_google_access_token(
    redis_client: redis.Redis,
    service_key: str,
    refresh_token: str,
) -> str:
    """Return a valid Google access token, refreshing and caching via Redis when expired.

    service_key — short identifier used in the cache key, e.g. "workspace", "ga4", "ads", "gbp"
    """
    cache_key = f"vance:gtoken:{service_key}"
    cached = redis_client.get(cache_key)
    if cached:
        return cached  # type: ignore[return-value]

    resp = httpx.post(
        _TOKEN_URL,
        data={
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    token: str = data["access_token"]
    expires_in = max(60, int(data.get("expires_in", 3600)) - 60)
    redis_client.setex(cache_key, expires_in, token)
    return token
