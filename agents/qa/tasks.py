"""Celery tasks for the qa agent."""

from __future__ import annotations

from shared.celery_app import app
from shared.logger import get_logger

logger = get_logger(__name__)


@app.task(name="agents.qa.tasks.run_regression_suite", bind=True, max_retries=1)
def run_regression_suite(self, product: str, triggered_by: str = "scheduled") -> dict:
    from agents._base import AgentConfig
    from agents.qa.main import QaAgent

    config = AgentConfig.load("qa")
    agent = QaAgent("qa", config)
    return agent._regression.run(product=product, triggered_by=triggered_by)


@app.task(name="agents.qa.tasks.coverage_report", bind=True, max_retries=1)
def coverage_report(self, repo: str) -> dict:
    from agents._base import AgentConfig
    from agents.qa.main import QaAgent

    config = AgentConfig.load("qa")
    agent = QaAgent("qa", config)
    return agent._coverage.report(repo=repo)


@app.task(name="agents.qa.tasks.health_ping", ignore_result=True)
def health_ping() -> None:
    from agents._base import AgentConfig
    from agents.qa.main import QaAgent

    try:
        config = AgentConfig.load("qa")
        agent = QaAgent("qa", config)
        healthy = agent.health_check()
        logger.info("qa_health_ping", healthy=healthy)
    except Exception as exc:
        logger.error("qa_health_ping_failed", error=str(exc))
