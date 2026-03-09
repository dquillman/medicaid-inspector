"""
Stripe billing routes — checkout sessions and webhook handling.

Set these environment variables:
  STRIPE_SECRET_KEY     — sk_test_... or sk_live_...
  STRIPE_WEBHOOK_SECRET — whsec_... (from Stripe dashboard)
  APP_URL               — e.g. http://localhost:5200 (for redirect URLs)
"""
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/billing", tags=["billing"])
log = logging.getLogger(__name__)

_STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
_APP_URL = os.environ.get("APP_URL", "http://localhost:5200")
_USERS_FILE = Path(__file__).parent.parent / "users.json"

# Price IDs — set these after creating products in Stripe dashboard
PRICE_IDS = {
    "starter": os.environ.get("STRIPE_PRICE_STARTER", ""),
    "professional": os.environ.get("STRIPE_PRICE_PROFESSIONAL", ""),
}


def _get_stripe():
    """Lazy import stripe to avoid hard dependency."""
    try:
        import stripe
        stripe.api_key = _STRIPE_KEY
        return stripe
    except ImportError:
        return None


class CheckoutRequest(BaseModel):
    plan: str
    email: str = ""


@router.post("/create-checkout")
async def create_checkout(req: CheckoutRequest):
    stripe = _get_stripe()
    if not stripe or not _STRIPE_KEY:
        raise HTTPException(
            503,
            "Stripe is not configured. Set STRIPE_SECRET_KEY environment variable.",
        )

    price_id = PRICE_IDS.get(req.plan)
    if not price_id:
        raise HTTPException(400, f"Unknown plan: {req.plan}")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=req.email or None,
            success_url=f"{_APP_URL}/?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{_APP_URL}/#pricing",
            metadata={"plan": req.plan},
        )
        return {"url": session.url, "session_id": session.id}
    except Exception as e:
        log.error("Stripe checkout error: %s", e)
        raise HTTPException(500, f"Payment error: {str(e)}")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks for subscription events."""
    stripe = _get_stripe()
    if not stripe or not _WEBHOOK_SECRET:
        raise HTTPException(503, "Stripe webhooks not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, _WEBHOOK_SECRET)
    except Exception as e:
        log.warning("Webhook signature verification failed: %s", e)
        raise HTTPException(400, "Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        email = (data.get("customer_email") or "").lower().strip()
        plan = data.get("metadata", {}).get("plan", "starter")
        if email:
            _update_user_plan(email, plan)
            log.info("Subscription activated: %s -> %s", email, plan)

    elif event_type == "customer.subscription.deleted":
        email = _get_email_from_customer(stripe, data.get("customer"))
        if email:
            _update_user_plan(email, "expired")
            log.info("Subscription cancelled: %s", email)

    return {"received": True}


@router.get("/plans")
async def get_plans():
    """Return available plans and whether Stripe is configured."""
    return {
        "stripe_configured": bool(_STRIPE_KEY),
        "plans": [
            {
                "id": "starter",
                "name": "Starter",
                "price": 4900,
                "currency": "usd",
                "interval": "month",
            },
            {
                "id": "professional",
                "name": "Professional",
                "price": 19900,
                "currency": "usd",
                "interval": "month",
            },
            {
                "id": "enterprise",
                "name": "Enterprise",
                "price": 0,
                "currency": "usd",
                "interval": "month",
                "custom": True,
            },
        ],
    }


def _update_user_plan(email: str, plan: str) -> None:
    try:
        users = json.loads(_USERS_FILE.read_text(encoding="utf-8")) if _USERS_FILE.exists() else {}
        if email in users:
            users[email]["plan"] = plan
            _USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")
    except Exception as e:
        log.error("Failed to update user plan: %s", e)


def _get_email_from_customer(stripe, customer_id: str) -> str:
    try:
        customer = stripe.Customer.retrieve(customer_id)
        return (customer.get("email") or "").lower().strip()
    except Exception:
        return ""
