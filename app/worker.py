from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import alpaca
from app.alpaca import AlpacaError
from app.db import SessionLocal
from app.entitlements import connection_payload, entitled
from app.models import Connection, PriceAlert, User, WorkerCursor, utcnow
from app.notifications import push


def run_once() -> None:
    db = SessionLocal()
    try:
        users = db.scalars(select(User)).all()
        for user in users:
            try:
                _scan_user(db, user)
            except Exception:
                db.rollback()
    finally:
        db.close()


def _cursor(db: Session, user: User) -> WorkerCursor:
    row = db.scalar(select(WorkerCursor).where(WorkerCursor.user_id == user.id))
    if not row:
        row = WorkerCursor(user_id=user.id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _scan_user(db: Session, user: User) -> None:
    conn = db.scalar(select(Connection).where(Connection.user_id == user.id))
    if not conn or not connection_payload(conn)["linked"]:
        _trial_nudge(db, user)
        return
    cur = _cursor(db, user)
    _fills_and_divs(db, user, conn, cur)
    if entitled(user):
        _upcoming_dividends(db, user, conn, cur)
        _price_alerts(db, user, conn)
        _options_expiry(db, user, conn)
    _trial_nudge(db, user)
    db.commit()


def _fills_and_divs(db: Session, user: User, conn: Connection, cur: WorkerCursor) -> None:
    try:
        activities = alpaca.get_activities(conn, "FILL,DIV,DIVCGL,DIVCGS,OPEXP,OPASN,OPXRC", page_size=50)
    except AlpacaError:
        return
    seen = cur.last_activity_id
    newest = seen
    for act in activities:
        aid = str(act.get("id") or "")
        if not newest:
            newest = aid
        if seen and aid == seen:
            break
        kind = str(act.get("activity_type") or "").upper()
        symbol = str(act.get("symbol") or "")
        if kind == "FILL":
            side = str(act.get("side") or "").lower()
            qty = act.get("qty") or act.get("leaves_qty") or ""
            price = act.get("price") or ""
            push(
                db,
                user,
                kind="fill",
                title=f"{symbol} {side} filled",
                body=f"{qty} @ {price}",
                symbol=symbol,
                href="/activity",
                dedupe_key=f"fill:{aid}",
            )
        elif kind.startswith("DIV"):
            net = act.get("net_amount") or act.get("per_share_amount") or ""
            push(
                db,
                user,
                kind="dividend",
                title=f"{symbol} dividend posted",
                body=f"Cash activity {net}",
                symbol=symbol,
                href="/dividends",
                dedupe_key=f"div:{aid}",
            )
        elif kind == "OPEXP":
            push(
                db,
                user,
                kind="options_expiry",
                title=f"{symbol} option expired",
                body="An options position reached expiration.",
                symbol=symbol,
                href="/options",
                dedupe_key=f"opexp:{aid}",
            )
        elif kind in {"OPASN", "OPXRC"}:
            push(
                db,
                user,
                kind="order",
                title=f"{symbol} option {kind.lower()}",
                body="Assignment or exercise posted to the account.",
                symbol=symbol,
                href="/activity",
                dedupe_key=f"op:{aid}",
            )
    if activities:
        cur.last_activity_id = str(activities[0].get("id") or newest or "")
    cur.last_order_check = utcnow()


def _upcoming_dividends(db: Session, user: User, conn: Connection, cur: WorkerCursor) -> None:
    now = utcnow()
    if cur.last_div_scan and (now - cur.last_div_scan) < timedelta(hours=12):
        return
    try:
        positions = alpaca.get_positions(conn)
    except AlpacaError:
        return
    symbols = sorted({str(p.get("symbol") or "") for p in positions if p.get("symbol") and len(str(p.get("symbol"))) <= 6})
    start = now.date().isoformat()
    end = (now + timedelta(days=45)).date().isoformat()
    for symbol in symbols[:30]:
        rows = alpaca.announcements_for_symbol(conn, symbol, start, end)
        for row in rows:
            ex_date = str(row.get("ex_date") or row.get("ex_dividend_date") or "")[:10]
            payable = str(row.get("payable_date") or "")[:10]
            cash = row.get("cash") or row.get("cash_amount") or row.get("rate")
            title = f"{symbol} goes ex-dividend {ex_date or 'soon'}"
            body = f"Estimated cash {cash}. Payable {payable or 'TBD'}."
            push(
                db,
                user,
                kind="dividend_upcoming",
                title=title,
                body=body,
                symbol=symbol,
                href="/dividends",
                dedupe_key=f"exdiv:{symbol}:{ex_date}",
            )
    cur.last_div_scan = now


def _price_alerts(db: Session, user: User, conn: Connection) -> None:
    alerts = db.scalars(select(PriceAlert).where(PriceAlert.user_id == user.id, PriceAlert.active.is_(True))).all()
    for alert in alerts:
        try:
            if "/" in alert.symbol:
                bars = alpaca.crypto_bars(conn, alert.symbol, "1Hour", 1)
                px = float((bars[-1] or {}).get("c") or 0) if bars else 0
            else:
                q = alpaca.latest_quote(conn, alert.symbol)
                bid = float(q.get("bp") or q.get("bid_price") or 0)
                ask = float(q.get("ap") or q.get("ask_price") or 0)
                px = ((bid + ask) / 2) if bid and ask else bid or ask
        except (AlpacaError, ValueError, TypeError):
            continue
        if not px:
            continue
        hit = (alert.op == "above" and px >= alert.price) or (alert.op == "below" and px <= alert.price)
        if not hit:
            continue
        push(
            db,
            user,
            kind="price",
            title=f"{alert.symbol} is {alert.op} {alert.price:g}",
            body=f"Last {px:.4g}",
            symbol=alert.symbol,
            href=f"/trade?symbol={alert.symbol}",
            dedupe_key=f"px:{alert.id}:{utcnow().date().isoformat()}",
        )
        alert.last_fired_at = utcnow()
        alert.active = False


def _options_expiry(db: Session, user: User, conn: Connection) -> None:
    try:
        positions = alpaca.get_positions(conn)
    except AlpacaError:
        return
    today = utcnow().date()
    for pos in positions:
        symbol = str(pos.get("symbol") or "")
        if len(symbol) < 15:
            continue
        # OCC: AAPL250117C00190000
        root = symbol[:-15] if len(symbol) > 15 else symbol[:6]
        yymmdd = symbol[len(root) : len(root) + 6]
        try:
            exp = datetime.strptime(yymmdd, "%y%m%d").date()
        except ValueError:
            continue
        days = (exp - today).days
        if days in {0, 1, 7}:
            push(
                db,
                user,
                kind="options_expiry",
                title=f"{symbol} expires in {days}d" if days else f"{symbol} expires today",
                body="Review close, roll, or exercise.",
                symbol=symbol,
                href="/options",
                dedupe_key=f"expiry:{symbol}:{exp.isoformat()}:{days}",
            )


def _trial_nudge(db: Session, user: User) -> None:
    from app.entitlements import subscription_active, trial_open
    from app.models import aware

    if subscription_active(user) or not trial_open(user):
        return
    days = (aware(user.trial_ends_at).date() - utcnow().date()).days
    if days in {3, 1, 0}:
        push(
            db,
            user,
            kind="trial",
            title="Cove trial ends soon" if days else "Cove trial ends today",
            body="Add a card to keep trading and alerts after the trial.",
            href="/upgrade",
            dedupe_key=f"trial:{user.id}:{days}",
        )
