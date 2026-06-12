"""Synchronous Postgres connection helper using psycopg2."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras

from shared.config.settings import settings


@contextmanager
def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """Yield a psycopg2 connection with auto-commit/rollback and guaranteed close."""
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
