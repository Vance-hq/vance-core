"""
Integration Agent — universal dispatcher for all external service calls.

Dispatch pattern:
    enqueue('integrations', 'call_service', {
        'service': 'github',
        'method':  'create_issue',
        'args':    {'repo': 'vance', 'title': 'Fix bug', 'body': '...'},
    })
"""
from __future__ import annotations

from agents._base import AgentConfig, BaseAgent
from shared.db.client import get_db
from shared.logger import get_logger
from shared.types import Task, TaskResult

from .registry import get_connector, list_services

logger = get_logger(__name__)


class IntegrationAgent(BaseAgent):
    def handle(self, task: Task) -> TaskResult:
        action = task.payload.get("action")
        if action == "call_service":
            output = self._call_service(task)
        elif action == "list_services":
            output = {"services": list_services()}
        else:
            raise ValueError(f"Unknown integrations action: {action!r}")
        return TaskResult(task_id=task.id, success=True, output=output)

    def health_check(self) -> bool:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM integration_calls LIMIT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------

    def _call_service(self, task: Task) -> dict:
        p = task.payload
        service: str = p["service"]
        method: str = p["method"]
        args: dict = p.get("args", {})

        connector_cls = get_connector(service)
        connector = connector_cls(
            task_id=task.id,
            called_by=self.agent_name,
            method_name=method,
        )

        fn = getattr(connector, method, None)
        if fn is None:
            raise ValueError(
                f"Connector '{service}' has no method '{method}'. "
                f"Check the connector class for supported methods."
            )

        logger.info(
            "integration_call",
            service=service,
            method=method,
            task_id=task.id,
        )

        result = fn(**args)
        return result if isinstance(result, dict) else {"result": result}


if __name__ == "__main__":
    config = AgentConfig.load("integrations")
    IntegrationAgent("integrations", config).run()
