"""
Vance Orchestrator — central routing brain.

Endpoints:
  POST /intent   Accept a VoiceIntent, route + dispatch, return receipt + spoken response
  GET  /status   Queue depths per agent, last 10 session entries, router stats
  GET  /health   Liveness check

Runs on port 7700 (local only — never exposed to the internet).
Start: python -m vance.core.orchestrator.main
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from shared.logger import get_logger
from .config import OrchestratorConfig
from .router import Router, UnknownIntentResult
from .dispatcher import Dispatcher
from .session import SessionContext

logger = get_logger(__name__)
config = OrchestratorConfig()

app = FastAPI(title="vance-orchestrator", version="0.2.0")

# Module-level singletons — shared across requests
_router = Router()
_dispatcher = Dispatcher()
_session = SessionContext(max_entries=10)


# ---------------------------------------------------------------------------
# Spoken response generation
# ---------------------------------------------------------------------------

_SPOKEN: dict[str, str] = {
    "marketing.generate_copy": "Writing that copy now.",
    "marketing.build_sequence": "Building the email sequence.",
    "marketing.create_campaign": "Launching that campaign.",
    "outreach.send_connection": "Sending the connection request.",
    "outreach.detect_replies": "Checking for replies.",
    "outreach.score_lead": "Scoring that lead.",
    "analytics.revenue_report": "Pulling revenue numbers.",
    "analytics.funnel_analysis": "Running funnel analysis.",
    "analytics.cohort_report": "Building the cohort report.",
    "dev.run_claude_code": "Running that Claude Code task.",
    "dev.git_push": "Committing and pushing.",
    "dev.deploy": "Triggering the deployment.",
    "security.check_uptime": "Running uptime checks.",
    "security.scan_logs": "Scanning the logs.",
    "security.send_alert": "Sending the alert.",
    "vance_system.status": "Here's the current status.",
    "vance_system.unknown": "I'm not sure what you mean. Can you rephrase?",
}


def _spoken_response(agent: str, action: str, product: str | None) -> str:
    key = f"{agent}.{action}"
    text = _SPOKEN.get(key)
    if not text:
        text = f"On it. Sending {action.replace('_', ' ')} to the {agent.replace('_', ' ')} agent."
    if product:
        text = text.rstrip(".") + f" for {product.replace('_', ' ')}."
    return text


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": "0.2.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/intent")
async def receive_intent(payload: dict[str, Any]) -> JSONResponse:
    """
    Accept a VoiceIntent JSON object from the voice layer.

    Runs: router → dispatcher → session.add → spoken response
    Returns: { task_ids, agents, actions, spoken_response, estimated_completion, session_context }
    """
    # Lazy import avoids loading TTS/audio libs at orchestrator startup
    from core.voice.intent.intent_schema import VoiceIntent

    try:
        intent = VoiceIntent(**payload)
    except Exception as e:
        logger.error("intent_validation_error", error=str(e))
        raise HTTPException(status_code=422, detail=str(e))

    raw_text = intent.raw_text

    # Route
    route_results = _router.route(
        raw_text=raw_text,
        structured_agent=intent.agent,
        structured_action=intent.action,
        confidence=intent.confidence,
    )

    # Unknown intent
    if isinstance(route_results, UnknownIntentResult):
        _dispatcher.dispatch_unknown(raw_text, route_results)
        spoken = "I'm not sure what you mean. Can you rephrase?"
        return JSONResponse({
            "task_ids": [],
            "agents": [],
            "actions": [],
            "spoken_response": spoken,
            "estimated_completion": None,
            "session_context": _session.get_context(5),
        })

    # Attach session context to intent payload before dispatch
    intent_payload = intent.model_dump(mode="json")
    intent_payload["session_context"] = _session.get_context(5)

    # Dispatch
    receipt = _dispatcher.dispatch(route_results, intent_payload)

    # Record in session
    primary = route_results[0]
    _session.add(
        intent_text=raw_text,
        intent_agent=primary.agent,
        intent_action=primary.action,
        product=intent.product,
        receipt=receipt,
    )

    spoken = _spoken_response(primary.agent, primary.action, intent.product)

    return JSONResponse({
        "task_ids": receipt.task_ids,
        "agents": receipt.agents,
        "actions": receipt.actions,
        "spoken_response": spoken,
        "estimated_completion": receipt.estimated_completion,
        "dispatched_at": receipt.dispatched_at,
        "session_context": _session.get_context(5),
    })


@app.post("/outcome")
async def update_outcome(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Called by agents when a task completes. Updates session history.

    Body: { task_id: str, outcome: "success"|"failed", detail?: str }
    """
    task_id = payload.get("task_id")
    outcome = payload.get("outcome", "success")
    detail = payload.get("detail")

    if not task_id:
        raise HTTPException(status_code=422, detail="task_id required")

    found = _session.update_outcome(task_id, outcome, detail)
    return {"updated": found, "task_id": task_id}


@app.get("/status")
async def status() -> dict[str, Any]:
    """Return session history and router stats."""
    return {
        "version": "0.2.0",
        "timestamp": datetime.utcnow().isoformat(),
        "session": {
            "entries": len(_session),
            "history": _session.get_context(),
        },
        "router": {
            "total_patterns": len(_router._patterns),
            "total_intents": len(_router._entries),
        },
    }


@app.post("/reload")
async def reload_config() -> dict[str, Any]:
    """Hot-reload routing_config.yaml without restarting."""
    _router.reload()
    return {"reloaded": True, "patterns": len(_router._patterns)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "core.orchestrator.main:app",
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level="info",
    )
