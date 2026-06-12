"""Stub heavy optional deps so tests run without external services."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

for _mod in ("boto3", "botocore", "botocore.exceptions"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
