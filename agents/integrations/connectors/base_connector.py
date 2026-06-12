"""Abstract base class for all integration connectors."""
from __future__ import annotations

import abc
import time
from urllib.parse import urlparse

import httpx
import redis

from shared.config.settings import settings
from shared.logger import get_logger

from ..audit_log import AuditLog

logger = get_logger(__name__)

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _path(url: str) -> str:
    return urlparse(url).path


class BaseConnector(abc.ABC):
    """One subclass per external service.  Provides rate-limiting, retry, and audit logging."""

    service_name: str = ""
    # (max_calls, window_seconds) — 0 calls means no limit enforced
    _rate_limit_config: tuple[int, int] = (0, 60)

    def __init__(
        self,
        task_id: str | None = None,
        called_by: str = "",
        method_name: str = "",
    ) -> None:
        self._task_id = task_id
        self._called_by = called_by
        self._method_name = method_name
        self._audit = AuditLog()
        self._redis = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB_QUEUE,
            decode_responses=True,
        )

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    @classmethod
    @abc.abstractmethod
    def load_credentials(cls) -> dict[str, str]:
        """Return a dict of credential values loaded from settings."""
        ...

    # ------------------------------------------------------------------
    # HTTP with retry + audit logging
    # ------------------------------------------------------------------

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        max_calls, window = self._rate_limit_config
        if max_calls:
            self.rate_limit(max_calls, window)

        kwargs.setdefault("timeout", 30.0)
        last_exc: Exception | None = None

        for attempt in range(3):
            t0 = time.monotonic()
            try:
                resp = httpx.request(method, url, **kwargs)
                self._log(
                    endpoint=_path(url),
                    status_code=resp.status_code,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    error_msg=None if resp.is_success else resp.text[:200],
                )
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in _RETRY_STATUS and attempt < 2:
                    time.sleep(2 ** attempt)
                    last_exc = exc
                    continue
                raise
            except httpx.RequestError as exc:
                self._log(
                    endpoint=_path(url),
                    status_code=0,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    error_msg=str(exc),
                )
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    last_exc = exc
                    continue
                raise

        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Rate limiting — Redis fixed-window counter
    # ------------------------------------------------------------------

    def rate_limit(self, calls: int, per_seconds: int = 60) -> None:
        window_key = int(time.time() // per_seconds)
        key = f"vance:ratelimit:{self.service_name}:{window_key}"
        count = int(self._redis.incr(key))
        if count == 1:
            self._redis.expire(key, per_seconds + 1)
        if count > calls:
            ttl = max(0, self._redis.ttl(key))
            raise RuntimeError(
                f"{self.service_name}: rate limit {calls}/{per_seconds}s hit. "
                f"Resets in {ttl}s."
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(
        self,
        endpoint: str,
        status_code: int,
        latency_ms: int,
        error_msg: str | None = None,
    ) -> None:
        self._audit.log(
            service=self.service_name,
            method=self._method_name,
            endpoint=endpoint,
            status_code=status_code,
            latency_ms=latency_ms,
            task_id=self._task_id,
            agent=self._called_by,
            error_msg=error_msg,
        )
