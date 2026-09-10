from __future__ import annotations

import json
import os
from datetime import timezone

import httpx
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import FEEDBACK_TO, NOTIFY_FROM, RESEND_API_KEY, ROOT
from app.entitlements import prefs
from app.models import Notification, User, utcnow


KIND_PREF = {
    "fill": "fills",
    "order": "orders",
    "dividend": "dividends",
    "dividend_upcoming": "dividend_upcoming",
    "price": "price_alerts",
    "options_expiry": "options_expiry",
    "trial": "trial",
}


def push(
    db: Session,
    user: User,
    *,
    kind: str,
    title: str,
    body: str = "",
    symbol: str = "",
    href: str = "",
    dedupe_key: str = "",
    send_email: bool = True,
) -> Notification | None:
    if kind != "test":
        pref_key = KIND_PREF.get(kind, kind)
        if not prefs(user).get(pref_key, True):
            return None
    row = Notification(
        user_id=user.id,
        kind=kind,
        title=title,
        body=body,
        symbol=symbol.upper(),
        href=href,
        dedupe_key=dedupe_key or f"{kind}:{symbol}:{title}:{utcnow().date().isoformat()}",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(row)
    if send_email:
        _email(user, title, body)
    return row


def unread_count(db: Session, user: User) -> int:
    from sqlalchemy import func, select

    return int(
        db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.user_id == user.id, Notification.read_at.is_(None)
            )
        )
        or 0
    )


def _from_address() -> str:
    raw = (NOTIFY_FROM or "").strip()
    if not raw or "localhost" in raw.lower():
        return "Alpaca Cove <onboarding@resend.dev>"
    return raw


def _resend_key() -> str:
    load_dotenv(ROOT / ".env", override=True)
    return os.getenv("RESEND_API_KEY", "").strip() or RESEND_API_KEY


def send_mail(to: str, title: str, body: str, reply_to: str = "") -> tuple[bool, str]:
    key = _resend_key()
    if not key:
        return False, "Email is not set up yet."
    if not to:
        return False, "No address to send to."
    payload = {
        "from": _from_address(),
        "to": [to],
        "subject": title,
        "text": body or title,
    }
    if reply_to and "@" in reply_to:
        payload["reply_to"] = [reply_to]
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=25.0,
        )
        if r.status_code < 400:
            return True, ""
        detail = ""
        try:
            data = r.json()
            detail = str((data or {}).get("message") or (data or {}).get("error") or "")
        except Exception:
            detail = (r.text or "")[:300]
        if not detail:
            detail = f"Email service said {r.status_code}."
        low = detail.lower()
        if "only send testing emails" in low or "verify a domain" in low:
            detail = (
                "Resend will only send to the Gmail you signed up with until a real sending domain is added. "
                + detail
            )
        return False, detail
    except Exception as exc:
        return False, str(exc) or "Could not reach the email service."


def send_alert_mail(user: User, title: str, body: str) -> tuple[bool, str]:
    seen: set[str] = set()
    last_err = "No address to send to."
    for addr in (user.email, FEEDBACK_TO):
        target = (addr or "").strip()
        key = target.lower()
        if not target or key in seen:
            continue
        seen.add(key)
        ok, err = send_mail(target, title, body)
        if ok:
            return True, ""
        last_err = err
    return False, last_err


def _email(user: User, title: str, body: str) -> bool:
    if not prefs(user).get("email_alerts", True):
        return False
    ok, _err = send_alert_mail(user, title, body)
    return ok


def send_feedback_mail(from_email: str, kind: str, message: str) -> tuple[bool, str, str]:
    title = f"Alpaca Cove {kind}: {from_email}"
    body = f"From: {from_email}\nKind: {kind}\n\n{message}"
    primary = (FEEDBACK_TO or "").strip()
    login = (from_email or "").strip()
    if primary:
        ok, err = send_mail(primary, title, body, reply_to=login)
        if ok:
            return True, "", primary
        if login and login.lower() != primary.lower():
            ok2, err2 = send_mail(login, title, body, reply_to=login)
            if ok2:
                return True, (
                    f"Could not send to {primary}. Resend testing only delivers to the Gmail "
                    f"you used to sign up. A copy went to {login} instead. {err}"
                ), login
            return False, err2 or err, ""
        return False, err, ""
    if login:
        ok, err = send_mail(login, title, body, reply_to=login)
        if ok:
            return True, "", login
        return False, err, ""
    return False, "No address to send to.", ""


def archive_feedback(user_key: str, kind: str, message: str) -> None:
    folder = ROOT / "data"
    folder.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"user": user_key, "kind": kind, "message": message}, ensure_ascii=False)
    with (folder / "feedback.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def serialize(row: Notification) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "symbol": row.symbol,
        "href": row.href,
        "read": bool(row.read_at),
        "created_at": row.created_at.astimezone(timezone.utc).isoformat() if row.created_at else "",
    }
