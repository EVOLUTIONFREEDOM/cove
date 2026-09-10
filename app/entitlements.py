from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from app.config import APP_SECRET
from app.models import Connection, User, aware


def _fernet() -> Fernet:
    digest = hashlib.sha256(APP_SECRET.encode("utf-8")).digest()
    import base64

    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_str(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_str(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""


def lifetime_paid(user: User) -> bool:
    return (user.stripe_subscription_id or "") == "lifetime" or (user.stripe_status or "").lower() == "lifetime"


def subscription_active(user: User) -> bool:
    if lifetime_paid(user):
        return True
    status = (user.stripe_status or "").lower()
    return status in {"trialing", "active"} and bool(user.stripe_subscription_id)


def trial_open(user: User) -> bool:
    return aware(user.trial_ends_at) > datetime.now(timezone.utc)


def entitled(user: User) -> bool:
    return trial_open(user) or subscription_active(user)


def entitlement_state(user: User) -> dict:
    now = datetime.now(timezone.utc)
    ends = aware(user.trial_ends_at)
    remaining = max(0, int((ends - now).total_seconds()))
    return {
        "ok": entitled(user),
        "trial": trial_open(user),
        "subscribed": subscription_active(user),
        "lifetime": lifetime_paid(user),
        "stripe_status": user.stripe_status or "",
        "trial_ends_at": ends.isoformat(),
        "trial_days_left": remaining // 86400,
        "can_trade": entitled(user),
    }


def connection_payload(conn: Connection | None) -> dict:
    if not conn:
        return {"linked": False, "paper": True, "account_tail": "", "status": ""}
    has_keys = bool(decrypt_str(conn.api_key_enc) and decrypt_str(conn.secret_enc))
    has_oauth = bool(decrypt_str(conn.oauth_token_enc))
    return {
        "linked": has_keys or has_oauth,
        "paper": conn.paper,
        "account_tail": conn.account_tail,
        "status": conn.account_status,
        "via": "oauth" if has_oauth and not has_keys else "keys" if has_keys else "",
    }


def prefs(user: User) -> dict:
    from app.models import prefs_dict

    defaults = {
        "fills": True,
        "orders": True,
        "dividends": True,
        "dividend_upcoming": True,
        "price_alerts": True,
        "options_expiry": True,
        "trial": True,
        "email_alerts": True,
    }
    defaults.update({k: bool(v) for k, v in prefs_dict(user).items()})
    return defaults


def save_prefs(user: User, incoming: dict) -> str:
    merged = prefs(user)
    for key in merged:
        if key in incoming:
            merged[key] = bool(incoming[key])
    user.notify_prefs = json.dumps(merged)
    return user.notify_prefs
