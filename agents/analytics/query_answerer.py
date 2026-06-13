"""QueryAnswerer — LLM-driven ad-hoc analytics queries for voice delivery."""

from __future__ import annotations

import json
import re
from typing import Any

from shared.db.client import get_db
from shared.llm.client import llm
from shared.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_HINT = """
Tables available:
- usage_snapshots(product, date, metrics JSONB)
- funnel_snapshots(product, date, step, count, conversion_rate_from_prev)
- cohort_data(product, cohort_month, cohort_size, day_30_retention, day_60_retention, day_90_retention)
- feature_usage(product, feature_name, week, unique_users, total_events, adoption_pct)
- engagement_scores(user_id, product, score, tier, calculated_at)
- ab_tests(agent, product, test_name, status, p_value, winner)
"""

_SQL_SYSTEM = (
    "You are a SQL analyst. Given a natural language question and the schema, "
    "produce a single safe read-only PostgreSQL SELECT query. "
    "Output JSON only: {\"sql\": \"SELECT ...\", \"description\": str}. "
    "Never use INSERT/UPDATE/DELETE/DROP. Limit results to 50 rows."
)

_VOICE_SYSTEM = (
    "You are a concise voice assistant. Given a question and SQL result rows, "
    "answer the question in 1-2 sentences. Put the number or key fact first. "
    "Example: '47 signups this week for OneServ, up from 31 last week.'"
)


class QueryAnswerer:

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    def run(self, question: str) -> dict[str, Any]:
        sql_resp = llm.complete(
            messages=[{"role": "user", "content": f"Schema:\n{_SCHEMA_HINT}\n\nQuestion: {question}"}],
            system=_SQL_SYSTEM,
            max_tokens=512,
        )
        raw_sql = sql_resp.content[0].text.strip()

        try:
            parsed = json.loads(raw_sql)
            sql = parsed.get("sql", "")
            description = parsed.get("description", "")
        except json.JSONDecodeError:
            match = re.search(r"SELECT\b.+", raw_sql, re.IGNORECASE | re.DOTALL)
            sql = match.group(0)[:1000] if match else ""
            description = ""

        if not sql or not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
            return {"error": "Could not generate a safe SQL query.", "question": question}

        rows = self._execute_sql(sql)
        answer = self._format_for_voice(question=question, rows=rows)

        logger.info("on_demand_query_answered", question=question[:80], rows=len(rows))
        return {
            "question": question,
            "sql": sql,
            "description": description,
            "row_count": len(rows),
            "answer": answer,
        }

    def _execute_sql(self, sql: str) -> list[dict[str, Any]]:
        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cols = [d[0] for d in cur.description]
                    return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as exc:
            logger.warning("ad_hoc_query_failed", error=str(exc))
            return []

    def _format_for_voice(self, question: str, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "No data found for that query."

        rows_text = json.dumps(rows[:10], default=str)
        resp = llm.complete(
            messages=[{"role": "user", "content": f"Question: {question}\nData: {rows_text}"}],
            system=_VOICE_SYSTEM,
            max_tokens=128,
        )
        return resp.content[0].text.strip()
