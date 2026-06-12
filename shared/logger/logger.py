"""Structured logging — all modules call get_logger(__name__)."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

try:
    import structlog
    _USE_STRUCTLOG = True
except ImportError:
    _USE_STRUCTLOG = False


class _KVLogger:
    """Thin wrapper that accepts structlog-style keyword args on stdlib logger."""

    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger

    def _fmt(self, msg: str, kw: dict[str, Any]) -> str:
        if not kw:
            return msg
        pairs = " ".join(f"{k}={v!r}" for k, v in kw.items())
        return f"{msg} {pairs}"

    def debug(self, msg: str, **kw: Any) -> None:
        self._log.debug(self._fmt(msg, kw))

    def info(self, msg: str, **kw: Any) -> None:
        self._log.info(self._fmt(msg, kw))

    def warning(self, msg: str, **kw: Any) -> None:
        self._log.warning(self._fmt(msg, kw))

    def error(self, msg: str, **kw: Any) -> None:
        self._log.error(self._fmt(msg, kw))


def get_logger(name: str) -> Any:
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    if _USE_STRUCTLOG:
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, level, logging.INFO)
            ),
        )
        return structlog.get_logger(name)

    base = logging.getLogger(name)
    if not base.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
        handler.setFormatter(logging.Formatter(fmt))
        base.addHandler(handler)
    base.setLevel(getattr(logging, level, logging.INFO))
    return _KVLogger(base)
