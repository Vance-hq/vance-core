"""Write every external API call to integration_calls for audit and analytics."""
from __future__ import annotations

from shared.db.client import get_db
from shared.logger import get_logger

logger = get_logger(__name__)


class AuditLog:
    def log(
        self,
        *,
        service: str,
        method: str,
        endpoint: str,
        status_code: int,
        latency_ms: int,
        task_id: str | None = None,
        agent: str = "",
        error_msg: str | None = None,
    ) -> None:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO integration_calls
                            (service, method, endpoint, status_code, latency_ms, task_id, agent, error_msg)
                        VALUES (%s, %s, %s, %s, %s, %s::uuid, %s, %s)
                        """,
                        (
                            service,
                            method,
                            endpoint,
                            status_code,
                            latency_ms,
                            task_id,
                            agent,
                            error_msg,
                        ),
                    )
        except Exception as exc:
            logger.warning("audit_log_write_failed", service=service, error=str(exc))
