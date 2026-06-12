"""
CustomerSentiment — monthly batch analysis of customer language.

Sources: support tickets, review text, NPS comments, email replies.
LLM identifies: pain points, desired features, customer phrases for copy.
Output: report stored in Postgres, top insights to strategy agent.
"""

from __future__ import annotations

import json
from typing import Any

from shared.llm.client import llm
from shared.logger import get_logger

from .db import ResearchDB

logger = get_logger(__name__)

_SENTIMENT_SYSTEM = (
    "You are a product researcher analysing customer feedback. "
    "Identify recurring themes across support tickets, NPS comments, and reviews. "
    "Reply with JSON only: "
    "{\"pain_points\": [str], \"desired_features\": [str], "
    "\"customer_phrases\": [str], \"overall_sentiment\": \"positive\"|\"mixed\"|\"negative\"}. "
    "customer_phrases are verbatim expressions customers use to describe the product — "
    "useful for copywriting."
)


def db_save_sentiment_report(product: str, report: dict[str, Any]) -> None:
    from shared.db.client import get_db
    import json as _json
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sentiment_reports (product, report_data)
                    VALUES (%s, %s)
                    """,
                    (product, _json.dumps(report)),
                )
    except Exception as exc:
        logger.warning("sentiment_report_save_failed", product=product, error=str(exc))


def enqueue_strategy_signal(
    product: str,
    pain_points: list[str],
    desired_features: list[str],
    customer_phrases: list[str],
) -> None:
    from shared.queue.queue import TaskQueue
    try:
        TaskQueue().push(
            agent="strategy",
            payload={
                "action": "sentiment_insights",
                "product": product,
                "pain_points": pain_points,
                "desired_features": desired_features,
                "customer_phrases": customer_phrases,
                "source": "research",
            },
        )
    except Exception as exc:
        logger.warning("enqueue_strategy_sentiment_failed", product=product, error=str(exc))


class CustomerSentiment:

    def __init__(self, db: ResearchDB, cfg: dict[str, Any]) -> None:
        self._db = db
        self._cfg = cfg

    def run(self, product: str) -> dict[str, Any]:
        inputs = self._db.get_sentiment_inputs(product=product)
        tickets = inputs.get("tickets", [])
        nps_comments = inputs.get("nps_comments", [])
        review_text = inputs.get("review_text", [])

        prompt = (
            f"Product: {product}\n\n"
            f"Support tickets ({len(tickets)}):\n"
            + "\n".join(f"- {t}" for t in tickets[:30])
            + f"\n\nNPS comments ({len(nps_comments)}):\n"
            + "\n".join(f"- {c}" for c in nps_comments[:30])
            + f"\n\nReview excerpts ({len(review_text)}):\n"
            + "\n".join(f"- {r}" for r in review_text[:30])
        )

        resp = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system=_SENTIMENT_SYSTEM,
            max_tokens=1024,
        )
        raw = resp.content[0].text.strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {
                "pain_points": [],
                "desired_features": [],
                "customer_phrases": [],
                "overall_sentiment": "neutral",
            }

        report = {
            "product": product,
            "pain_points": parsed.get("pain_points", []),
            "desired_features": parsed.get("desired_features", []),
            "customer_phrases": parsed.get("customer_phrases", []),
            "overall_sentiment": parsed.get("overall_sentiment", "neutral"),
        }

        db_save_sentiment_report(product=product, report=report)

        enqueue_strategy_signal(
            product=product,
            pain_points=report["pain_points"],
            desired_features=report["desired_features"],
            customer_phrases=report["customer_phrases"],
        )

        logger.info("customer_sentiment_complete", product=product, sentiment=report["overall_sentiment"])
        return report
