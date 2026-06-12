"""Stub optional runtime deps so tests run without a live stack."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

for _mod in ("celery", "celery.schedules", "redis"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
