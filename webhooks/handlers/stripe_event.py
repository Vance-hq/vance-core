"""Stripe webhook event handler.

Verifies the Stripe signature, then routes to the appropriate agent task.
This handler does NOT use the shared X-Vance-Hook-Secret — Stripe sends its
own HMAC signature via the Stripe-Signature header instead.
"""

from __future__ import annotations

import stripe
from fastapi import HTTPException, Request

from shared.config.settings import settings
from shared.logger import get_logger
from shared.queue.queue import TaskQueue

logger = get_logger(__name__)

_PRIORITY_HIGH = 3
_PRIORITY_NORMAL = 5

_queue = TaskQueue()


async def handle_stripe_event(request: Request) -> dict[str, str]:
    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # ------------------------------------------------------------------
    # Verify signature — protects against spoofed Stripe events
    # ------------------------------------------------------------------
    try:
        event = stripe.Webhook.construct_event(
            payload=raw_body,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except stripe.SignatureVerificationError:
        logger.warning("stripe_signature_invalid")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as exc:
        logger.error("stripe_event_parse_error", error=str(exc))
        raise HTTPException(status_code=400, detail="Bad payload")

    event_type: str = event["type"]
    data: dict = event["data"]["object"]

    logger.info("stripe_event_received", event_type=event_type, event_id=event["id"])

    if event_type == "checkout.session.completed":
        _on_checkout_completed(data)
    elif event_type == "customer.subscription.created":
        _on_subscription_created(data)
    elif event_type == "customer.subscription.deleted":
        _on_subscription_deleted(data)
    else:
        logger.info("stripe_event_unhandled", event_type=event_type)

    return {"status": "ok", "event_type": event_type}


def _on_checkout_completed(session: dict) -> None:
    task_id = _queue.push(
        agent="analytics",
        payload={
            "action": "revenue_report",
            "trigger": "checkout.session.completed",
            "session_id": session.get("id"),
            "customer_id": session.get("customer"),
            "amount_total": session.get("amount_total"),
            "currency": session.get("currency"),
        },
        priority=_PRIORITY_NORMAL,
    )
    logger.info("analytics_task_enqueued", trigger="checkout_completed", task_id=task_id)


def _on_subscription_created(subscription: dict) -> None:
    task_id = _queue.push(
        agent="analytics",
        payload={
            "action": "revenue_report",
            "trigger": "customer.subscription.created",
            "subscription_id": subscription.get("id"),
            "customer_id": subscription.get("customer"),
            "plan": subscription.get("items", {}).get("data", [{}])[0].get("price", {}).get("id"),
            "status": subscription.get("status"),
        },
        priority=_PRIORITY_NORMAL,
    )
    logger.info("analytics_task_enqueued", trigger="subscription_created", task_id=task_id)


def _on_subscription_deleted(subscription: dict) -> None:
    customer_id = subscription.get("customer")
    subscription_id = subscription.get("id")

    # Update MRR
    _queue.push(
        agent="analytics",
        payload={
            "action": "revenue_report",
            "trigger": "customer.subscription.deleted",
            "subscription_id": subscription_id,
            "customer_id": customer_id,
        },
        priority=_PRIORITY_NORMAL,
    )

    # Trigger cancellation recovery sequence
    task_id = _queue.push(
        agent="marketing",
        payload={
            "action": "build_sequence",
            "goal": "win-back cancelled subscriber",
            "audience": f"cancelled customer {customer_id}",
            "steps": 3,
            "trigger": "subscription_cancelled",
            "subscription_id": subscription_id,
            "customer_id": customer_id,
        },
        priority=_PRIORITY_HIGH,
    )
    logger.info(
        "cancellation_recovery_enqueued",
        customer_id=customer_id,
        task_id=task_id,
    )
