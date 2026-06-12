"""Stub out optional runtime deps (boto3, weasyprint) so tests run without them."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

for _mod in ("boto3", "botocore", "botocore.exceptions", "weasyprint"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
