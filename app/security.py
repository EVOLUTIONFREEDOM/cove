from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone

from cryptography.fernet import Fernet

from app.config import APP_SECRET, TRIAL_DAYS


def _fernet() -> Fernet:
    digest = hashlib.sha256(APP_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, hexdigest = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return hmac.compare_digest(dk.hex(), hexdigest)


def trial_end() -> datetime:
    from datetime import timedelta

    return datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)


def entitlement(user) -> dict:
    now = datetime.now(timezone.utc)
    trial_ends = user.trial_ends_at
    if trial_ends.tzinfo is None:
        trial_ends = trial_ends.replace(tzinfo=timezone.utc)
    trial_ok = now < trial_ends
    paid = (user.stripe_subscription_id == "lifetime") or (
        user.stripe_status in {"trialing", "active"} and bool(user.stripe_subscription_id)
    )
    ok = trial_ok or paid
    days_left = max(0, int((trial_ends - now).total_seconds() // 86400))
    return {
        "ok": ok,
        "trial_ok": trial_ok,
        "paid": paid,
        "days_left": days_left,
        "status": user.stripe_status,
        "trial_ends_at": trial_ends.isoformat(),
    }
