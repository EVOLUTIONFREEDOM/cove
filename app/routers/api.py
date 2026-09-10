from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse, RedirectResponse

from app import alpaca, billing, services
from app.alpaca import AlpacaError
from app.accounts import wipe_user
from app.auth import current_user, logout_user, verify_password
from app.config import ALPACA_OAUTH_CLIENT_ID, APP_NAME, APP_VERSION, COMPANY_NAME, FEEDBACK_TO, PUBLIC_SITE_URL, RESEND_API_KEY, SHARE_URL, STRIPE_PRICE_AMOUNT, STRIPE_PRICE_LIFETIME_CENTS, TRIAL_DAYS
from app.db import get_db
from app.entitlements import (
    connection_payload,
    decrypt_str,
    encrypt_str,
    entitlement_state,
    entitled,
    prefs,
    save_prefs,
)
from app.models import Connection, Feedback, Notification, PriceAlert, User, WatchItem, utcnow
from app.notifications import archive_feedback, send_alert_mail, send_feedback_mail, serialize, unread_count, push
from app.worker import run_once

router = APIRouter()


def _user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def _conn(user: User) -> Connection:
    if not user.connection or not connection_payload(user.connection)["linked"]:
        raise HTTPException(status_code=400, detail="Link your Alpaca account first")
    return user.connection


def _alpaca_user_error(exc: AlpacaError) -> str:
    raw = str(exc)
    if exc.status == 401 or "unauthorized" in raw.lower():
        return (
            "Alpaca rejected the saved API keys. Open Account and paste a new Paper key "
            "(it starts with PK) and the matching secret."
        )
    return raw


def err(exc: AlpacaError) -> JSONResponse:
    status = 400 if exc.status == 401 else (min(exc.status, 499) if exc.status >= 400 else 400)
    return JSONResponse(
        {"ok": False, "error": _alpaca_user_error(exc), "alpaca_status": exc.status},
        status_code=status,
    )


@router.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    return {
        "ok": True,
        "email": user.email,
        "entitlement": entitlement_state(user),
        "connection": connection_payload(user.connection),
        "unread": unread_count(db, user),
        "prefs": prefs(user),
        "oauth_configured": bool(ALPACA_OAUTH_CLIENT_ID),
        "app_name": APP_NAME,
        "company": COMPANY_NAME,
        "version": APP_VERSION,
        "share_url": SHARE_URL,
        "public_site_url": PUBLIC_SITE_URL,
        "feedback_email": FEEDBACK_TO,
        "site_upgrade_url": PUBLIC_SITE_URL,
        "site_share_url": PUBLIC_SITE_URL,
        "site_feedback_url": f"mailto:{FEEDBACK_TO}",
        "site_readme_url": f"{PUBLIC_SITE_URL}/terms-and-conditions/",
        "share_text": (
            f"{APP_NAME} is an iPhone and Android desk for people who already have Alpaca. "
            f"{TRIAL_DAYS} days free, then ${STRIPE_PRICE_AMOUNT / 100:.2f} a month or "
            f"${STRIPE_PRICE_LIFETIME_CENTS / 100:.0f} once. Trades stay on Alpaca. "
            f"Made by {COMPANY_NAME}."
        ),
        "trial_days": TRIAL_DAYS,
        "price_label": f"${STRIPE_PRICE_AMOUNT / 100:.2f}",
        "lifetime_label": f"${STRIPE_PRICE_LIFETIME_CENTS / 100:.0f}",
        "stripe_ready": billing.stripe_ready(),
    }


class KeysIn(BaseModel):
    api_key: str
    secret_key: str
    paper: bool = True


@router.post("/api/connect/keys")
def connect_keys(body: KeysIn, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    paper = bool(body.paper)
    conn = user.connection or Connection(user_id=user.id, paper=paper)
    conn.api_key_enc = encrypt_str(body.api_key.strip())
    conn.secret_enc = encrypt_str(body.secret_key.strip())
    conn.paper = paper
    db.add(conn)
    db.commit()
    db.refresh(conn)
    try:
        acct = alpaca.get_account(conn)
    except AlpacaError as exc:
        return err(exc)
    conn.account_tail = str(acct.get("account_number") or "")[-4:]
    conn.account_status = str(acct.get("status") or "")
    db.commit()
    return {"ok": True, "connection": connection_payload(conn), "account": services.snapshot(conn)["account"]}


@router.post("/api/connect/disconnect")
def disconnect(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    if user.connection:
        db.delete(user.connection)
        db.commit()
    return {"ok": True}


@router.get("/connect/alpaca")
def connect_oauth(request: Request, env: str = "paper", db: Session = Depends(get_db)):
    user = _user(request, db)
    if env not in {"paper", "live"}:
        env = "paper"
    import secrets

    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_env"] = env
    try:
        url = alpaca.oauth_authorize_url(state, env)
    except AlpacaError as exc:
        request.session["flash"] = str(exc)
        return RedirectResponse("/account", status_code=302)
    _ = user
    return RedirectResponse(url, status_code=302)


@router.get("/auth/alpaca/callback")
def oauth_callback(request: Request, code: str = "", state: str = "", db: Session = Depends(get_db)):
    user = _user(request, db)
    if not code or state != request.session.get("oauth_state"):
        request.session["flash"] = "Alpaca authorization failed."
        return RedirectResponse("/account", status_code=302)
    env = request.session.get("oauth_env") or "paper"
    try:
        token = alpaca.oauth_exchange(code)
    except AlpacaError as exc:
        request.session["flash"] = str(exc)
        return RedirectResponse("/account", status_code=302)
    conn = user.connection or Connection(user_id=user.id)
    conn.oauth_token_enc = encrypt_str(token.get("access_token") or "")
    conn.paper = env != "live"
    db.add(conn)
    db.commit()
    db.refresh(conn)
    try:
        acct = alpaca.get_account(conn)
        conn.account_tail = str(acct.get("account_number") or "")[-4:]
        conn.account_status = str(acct.get("status") or "")
        db.commit()
    except AlpacaError as exc:
        request.session["flash"] = str(exc)
    return RedirectResponse("/home", status_code=302)


@router.get("/api/snapshot")
def snapshot(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    try:
        data = services.snapshot(_conn(user))
        data["ok"] = True
        return data
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/history")
def history(request: Request, period: str = "1M", db: Session = Depends(get_db)):
    user = _user(request, db)
    try:
        data = services.history_points(_conn(user), period=period)
        data["ok"] = True
        return data
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/orders")
def orders(request: Request, status: str = "all", db: Session = Depends(get_db)):
    user = _user(request, db)
    try:
        return {"ok": True, "orders": alpaca.get_orders(_conn(user), status=status)}
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/activities")
def activities(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    try:
        return {"ok": True, "activities": alpaca.get_activities(_conn(user), page_size=80)}
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/bars")
def bars(request: Request, symbol: str, timeframe: str = "1Day", db: Session = Depends(get_db)):
    user = _user(request, db)
    conn = _conn(user)
    symbol = symbol.upper().strip()
    allowed = {"1Min", "5Min", "15Min", "30Min", "1Hour", "1Day", "1Week", "1Month", "YTD", "180D", "1Y", "3Y", "MAX"}
    timeframe = timeframe if timeframe in allowed else "1Day"
    try:
        rows = alpaca.crypto_bars(conn, symbol, timeframe) if "/" in symbol else alpaca.stock_bars(conn, symbol, timeframe)
        return {"ok": True, "symbol": symbol, "timeframe": timeframe, "bars": rows}
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/asset")
def asset(request: Request, symbol: str, db: Session = Depends(get_db)):
    user = _user(request, db)
    conn = _conn(user)
    symbol = symbol.upper().strip()
    out: dict = {"ok": True, "symbol": symbol}
    try:
        if "/" in symbol:
            out["asset"] = {"symbol": symbol, "class": "crypto", "tradable": True, "fractionable": True}
            out["bars"] = alpaca.crypto_bars(conn, symbol)
        else:
            out["asset"] = alpaca.get_asset(conn, symbol)
            out["bars"] = alpaca.stock_bars(conn, symbol)
            try:
                out["quote"] = alpaca.market_quote(conn, symbol)
            except AlpacaError:
                out["quote"] = {}
            try:
                out["news"] = alpaca.news(conn, symbol)
            except AlpacaError:
                out["news"] = []
        return out
    except AlpacaError as exc:
        return err(exc)


class OrderIn(BaseModel):
    symbol: str
    side: str = "buy"
    type: str = "market"
    qty: str | float | None = None
    notional: str | float | None = None
    time_in_force: str | None = None
    limit_price: str | float | None = None
    stop_price: str | float | None = None
    trail_price: str | float | None = None
    trail_percent: str | float | None = None
    extended_hours: bool = False
    asset_class: str = "us_equity"
    position_intent: str | None = None
    order_class: str | None = None
    legs: list[dict] | None = None


@router.post("/api/orders")
def place_order(body: OrderIn, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    if not entitled(user):
        raise HTTPException(status_code=402, detail="Trial ended. Subscribe to keep trading.")
    conn = _conn(user)
    try:
        payload = services.build_order(body.model_dump())
        order = alpaca.submit_order(conn, payload)
        push(
            db,
            user,
            kind="order",
            title=f"Order submitted · {payload.get('symbol') or 'multi-leg'}",
            body=f"{payload.get('side', '')} {payload.get('qty') or payload.get('notional') or ''}",
            symbol=str(payload.get("symbol") or ""),
            href="/activity",
            dedupe_key=f"order:{order.get('id')}",
        )
        return {"ok": True, "order": order}
    except AlpacaError as exc:
        return err(exc)


@router.delete("/api/orders/{order_id}")
def cancel(order_id: str, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    if not entitled(user):
        raise HTTPException(status_code=402, detail="Subscribe to manage orders.")
    try:
        alpaca.cancel_order(_conn(user), order_id)
        return {"ok": True}
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/options/chain")
def options_chain(request: Request, underlying: str, expiration: str | None = None, db: Session = Depends(get_db)):
    user = _user(request, db)
    try:
        data = services.option_chain_view(_conn(user), underlying, expiration)
        data["ok"] = True
        return data
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/calendar/pnl")
def calendar_pnl(request: Request, year: int | None = None, month: int | None = None, db: Session = Depends(get_db)):
    user = _user(request, db)
    today = date.today()
    try:
        data = services.pnl_calendar(_conn(user), year or today.year, month or today.month)
        data["ok"] = True
        return data
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/calendar/dividends")
def calendar_div(request: Request, year: int | None = None, month: int | None = None, db: Session = Depends(get_db)):
    user = _user(request, db)
    today = date.today()
    try:
        data = services.dividend_events(_conn(user), year or today.year, month or today.month)
        data["ok"] = True
        return data
    except AlpacaError as exc:
        return err(exc)


@router.get("/api/watchlist")
def watchlist(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    items = db.scalars(select(WatchItem).where(WatchItem.user_id == user.id)).all()
    symbols = [i.symbol for i in items]
    linked = bool(user.connection and connection_payload(user.connection)["linked"])
    if not linked:
        return {"ok": True, "linked": False, "items": [{"symbol": s, "name": s, "price": None, "change_pct": None, "bars": []} for s in symbols]}
    return {"ok": True, "linked": True, "items": services.watchlist_rows(user.connection, symbols)}


class WatchIn(BaseModel):
    symbol: str


@router.post("/api/watchlist")
def watch_add(body: WatchIn, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    symbol = body.symbol.upper().strip()
    if not db.scalar(select(WatchItem).where(WatchItem.user_id == user.id, WatchItem.symbol == symbol)):
        db.add(WatchItem(user_id=user.id, symbol=symbol))
        db.commit()
    return {"ok": True}


@router.delete("/api/watchlist/{symbol}")
def watch_del(symbol: str, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    row = db.scalar(select(WatchItem).where(WatchItem.user_id == user.id, WatchItem.symbol == symbol.upper()))
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.get("/api/alerts")
def list_alerts(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    rows = db.scalars(select(PriceAlert).where(PriceAlert.user_id == user.id)).all()
    notes = db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(80)
    ).all()
    return {
        "ok": True,
        "price_alerts": [
            {"id": r.id, "symbol": r.symbol, "op": r.op, "price": r.price, "active": r.active} for r in rows
        ],
        "notifications": [serialize(n) for n in notes],
        "prefs": prefs(user),
    }


class AlertIn(BaseModel):
    symbol: str
    op: str = "above"
    price: float


@router.post("/api/alerts")
def add_alert(body: AlertIn, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    if body.op not in {"above", "below"}:
        raise HTTPException(status_code=400, detail="op must be above or below")
    db.add(PriceAlert(user_id=user.id, symbol=body.symbol.upper().strip(), op=body.op, price=float(body.price)))
    db.commit()
    return {"ok": True}


@router.delete("/api/alerts/{alert_id}")
def del_alert(alert_id: int, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    row = db.get(PriceAlert, alert_id)
    if row and row.user_id == user.id:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.post("/api/notifications/{nid}/read")
def read_note(nid: int, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    row = db.get(Notification, nid)
    if row and row.user_id == user.id:
        row.read_at = utcnow()
        db.commit()
    return {"ok": True}


@router.post("/api/notifications/read-all")
def read_all(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))).all()
    now = utcnow()
    for row in rows:
        row.read_at = now
    db.commit()
    return {"ok": True}


@router.post("/api/alerts/test-email")
def test_alert_email(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    if not prefs(user).get("email_alerts", True):
        return {"ok": False, "error": "Turn on Email alerts first, then tap Send test email."}
    ok, err = send_alert_mail(
        user,
        "Alpaca Cove test email",
        "This is a test from Alerts. If you can read this, email alerts are working for this login.",
    )
    if ok:
        return {"ok": True, "sent_to": user.email}
    return {"ok": False, "error": err or "Email did not send."}


class PrefsIn(BaseModel):
    fills: bool | None = None
    orders: bool | None = None
    dividends: bool | None = None
    dividend_upcoming: bool | None = None
    price_alerts: bool | None = None
    options_expiry: bool | None = None
    trial: bool | None = None
    email_alerts: bool | None = None


@router.post("/api/prefs")
def set_prefs(body: PrefsIn, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    save_prefs(user, body.model_dump(exclude_none=True))
    db.commit()
    return {"ok": True, "prefs": prefs(user)}


class CheckoutIn(BaseModel):
    plan: str = "monthly"


class FeedbackIn(BaseModel):
    kind: str = "idea"
    message: str


class DeleteAccountIn(BaseModel):
    password: str


@router.post("/api/account/delete")
def delete_account_api(body: DeleteAccountIn, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    if not verify_password(body.password or "", user.password_hash):
        return {"ok": False, "error": "Password is wrong."}
    wipe_user(db, user)
    logout_user(request)
    return {"ok": True}


@router.post("/api/feedback")
def send_feedback(body: FeedbackIn, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    kind = (body.kind or "idea").strip().lower()
    if kind not in {"idea", "problem", "other"}:
        kind = "idea"
    message = (body.message or "").strip()
    if len(message) < 8:
        return {"ok": False, "error": "Write a little more so it is useful."}
    if len(message) > 4000:
        return {"ok": False, "error": "Keep it under 4000 characters."}
    mailed, mail_error, sent_to = send_feedback_mail(user.email, kind, message)
    archive_feedback(user.email, kind, message)
    db.add(Feedback(user_id=user.id, kind=kind, message=message, emailed=mailed))
    db.commit()
    if mailed:
        return {
            "ok": True,
            "emailed": True,
            "sent_to": sent_to,
            "notice": mail_error or "",
        }
    return {
        "ok": True,
        "emailed": False,
        "error": mail_error or "Saved in the app, but the email did not send.",
    }


@router.post("/api/billing/checkout")
def checkout(body: CheckoutIn, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    if not billing.stripe_ready():
        return {"ok": False, "error": "Pay in the App Store or Google Play when those products are live."}
    url = billing.checkout_url(user, body.plan)
    db.commit()
    return {"ok": True, "url": url}


@router.post("/api/billing/portal")
def portal(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    if not billing.stripe_ready() or not user.stripe_customer_id:
        return {"ok": False, "error": "On a phone, restore from your Apple or Google account when the store products are live."}
    return {"ok": True, "url": billing.portal_url(user)}


@router.post("/api/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    from app.config import STRIPE_WEBHOOK_SECRET
    import stripe

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=400, detail="Webhook secret missing")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    obj = event["data"]["object"]
    customer = obj.get("customer")
    if event["type"].startswith("customer.subscription"):
        user = db.scalar(select(User).where(User.stripe_customer_id == str(customer or "")))
        if user:
            billing.apply_subscription(user, obj)
            db.commit()
    if event["type"] == "checkout.session.completed":
        user = db.scalar(select(User).where(User.stripe_customer_id == str(customer or "")))
        if user:
            meta = obj.get("metadata") or {}
            if obj.get("mode") == "payment" or meta.get("plan") == "lifetime":
                billing.apply_lifetime(user, customer)
            elif obj.get("subscription"):
                user.stripe_subscription_id = str(obj.get("subscription"))
                user.stripe_status = "active"
            db.commit()
    return {"ok": True}


@router.post("/api/cron/tick")
def cron_tick():
    run_once()
    return {"ok": True}
