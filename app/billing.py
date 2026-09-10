from __future__ import annotations

from datetime import datetime, timezone

import stripe
from fastapi import HTTPException

from app.config import APP_URL, STRIPE_PRICE_ID, STRIPE_PRICE_LIFETIME_ID, STRIPE_SECRET_KEY
from app.entitlements import trial_open
from app.models import User, aware


def stripe_ready() -> bool:
    return bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)


def _client() -> None:
    if not stripe_ready():
        raise HTTPException(status_code=400, detail="Stripe is not configured")
    stripe.api_key = STRIPE_SECRET_KEY


def ensure_customer(user: User) -> str:
    _client()
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(email=user.email, metadata={"cove_user_id": str(user.id)})
    user.stripe_customer_id = customer.id
    return customer.id


def checkout_url(user: User, plan: str = "monthly") -> str:
    _client()
    customer = ensure_customer(user)
    plan = (plan or "monthly").lower()
    if plan == "lifetime":
        if not STRIPE_PRICE_LIFETIME_ID:
            raise HTTPException(status_code=400, detail="Lifetime price is not set yet")
        session = stripe.checkout.Session.create(
            mode="payment",
            customer=customer,
            line_items=[{"price": STRIPE_PRICE_LIFETIME_ID, "quantity": 1}],
            success_url=f"{APP_URL}/upgrade?billing=success",
            cancel_url=f"{APP_URL}/upgrade?billing=cancel",
            allow_promotion_codes=True,
            metadata={"plan": "lifetime", "cove_user_id": str(user.id)},
        )
    else:
        if not STRIPE_PRICE_ID:
            raise HTTPException(status_code=400, detail="Monthly price is not set yet")
        extra: dict = {}
        if trial_open(user):
            remaining = max(1, int((aware(user.trial_ends_at) - datetime.now(timezone.utc)).total_seconds() // 86400))
            extra["subscription_data"] = {"trial_period_days": min(remaining, 30)}
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer,
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            success_url=f"{APP_URL}/upgrade?billing=success",
            cancel_url=f"{APP_URL}/upgrade?billing=cancel",
            allow_promotion_codes=True,
            metadata={"plan": "monthly", "cove_user_id": str(user.id)},
            **extra,
        )
    if not session.url:
        raise HTTPException(status_code=500, detail="Stripe did not return a checkout URL")
    return session.url


def portal_url(user: User) -> str:
    _client()
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing customer yet")
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{APP_URL}/upgrade",
    )
    return session.url


def apply_subscription(user: User, sub: dict) -> None:
    user.stripe_subscription_id = str(sub.get("id") or user.stripe_subscription_id)
    user.stripe_status = str(sub.get("status") or "")
    customer = sub.get("customer")
    if customer:
        user.stripe_customer_id = str(customer)


def apply_lifetime(user: User, customer: str | None = None) -> None:
    user.stripe_subscription_id = "lifetime"
    user.stripe_status = "active"
    if customer:
        user.stripe_customer_id = str(customer)
