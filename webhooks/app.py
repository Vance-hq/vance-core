"""Vance webhook server — inbound event layer for external services.

Exposed via Nginx at /hooks/. All endpoints except /health and /hooks/stripe/event
require the X-Vance-Hook-Secret header. Stripe uses its own HMAC signature scheme.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from shared.logger import get_logger

from webhooks.handlers.grader_submit import handle_grader_submit
from webhooks.handlers.grader_track import handle_click_event, handle_open_event
from webhooks.handlers.mailcow_reply import handle_mailcow_reply
from webhooks.handlers.stripe_event import handle_stripe_event
from webhooks.middleware.auth import verify_hook_secret

logger = get_logger(__name__)

app = FastAPI(title="vance-webhooks", version="0.1.0")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "vance-webhooks"}


# ---------------------------------------------------------------------------
# Mailcow reply
# ---------------------------------------------------------------------------

@app.post("/hooks/mailcow/reply", dependencies=[Depends(verify_hook_secret)])
def mailcow_reply(payload: dict[str, Any]) -> JSONResponse:
    result = handle_mailcow_reply(payload)
    return JSONResponse(content=result, status_code=200)


# ---------------------------------------------------------------------------
# Stripe events — no shared secret, uses Stripe HMAC signature verification
# ---------------------------------------------------------------------------

@app.post("/hooks/stripe/event")
async def stripe_event(request: Request) -> JSONResponse:
    result = await handle_stripe_event(request)
    return JSONResponse(content=result, status_code=200)


# ---------------------------------------------------------------------------
# LocalRankGrader — public form submission (no auth: top-of-funnel entry)
# ---------------------------------------------------------------------------

@app.post("/hooks/grader/submit")
async def grader_submit(request: Request) -> JSONResponse:
    body = await request.json()
    result = handle_grader_submit(body)
    return JSONResponse(content=result, status_code=202)


# ---------------------------------------------------------------------------
# LocalRankGrader — email open pixel (no auth: embedded in emails)
# ---------------------------------------------------------------------------

@app.get("/hooks/grader/open/{lead_id}/{step_gif}")
def grader_open_pixel(lead_id: str, step_gif: str) -> Response:
    step = int(step_gif.replace(".gif", "")) if step_gif.endswith(".gif") else 1
    gif_bytes = handle_open_event(lead_id, step)
    return Response(content=gif_bytes, media_type="image/gif")


# ---------------------------------------------------------------------------
# LocalRankGrader — click tracking redirect (no auth: embedded in emails)
# ---------------------------------------------------------------------------

@app.get("/hooks/grader/click/{lead_id}")
def grader_click(lead_id: str, to: str = "", pricing: int = 0) -> RedirectResponse:
    result = handle_click_event(lead_id, to_url=to, pricing=bool(pricing))
    return RedirectResponse(url=result["redirect_to"], status_code=302)


# ---------------------------------------------------------------------------
# Generic catch-all for future integrations
# ---------------------------------------------------------------------------

@app.post("/hooks/generic/{source}", dependencies=[Depends(verify_hook_secret)])
async def generic_hook(source: str, request: Request) -> JSONResponse:
    body = await request.json()
    logger.info("generic_hook_received", source=source, keys=list(body.keys()))
    # Placeholder — wire to specific handlers as new integrations are added
    return JSONResponse(content={"status": "received", "source": source}, status_code=200)
