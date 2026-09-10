from __future__ import annotations

import uuid
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any

from app import alpaca
from app.alpaca import AlpacaError
from app.models import Connection

try:
    from zoneinfo import ZoneInfo

    EASTERN = ZoneInfo("America/New_York")
except Exception:
    EASTERN = timezone(timedelta(hours=-4))


def _parse_et(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(EASTERN)


def market_session(clock: dict) -> dict:
    """Regular, pre-market, after-hours, or closed. Alpaca is_open is regular session only."""
    now = _parse_et(clock.get("timestamp")) or datetime.now(EASTERN)
    t = now.time().replace(tzinfo=None)
    weekday = now.weekday() < 5
    if clock.get("is_open"):
        return {
            "is_open": True,
            "extended": False,
            "session": "regular",
            "label": "Market open",
            "hint": "Regular hours · 9:30 am–4:00 pm ET",
        }
    if weekday and dtime(4, 0) <= t < dtime(9, 30):
        return {
            "is_open": False,
            "extended": True,
            "session": "pre",
            "label": "Pre-market",
            "hint": "4:00 am–9:30 am ET · limit orders, extended hours",
        }
    if weekday and dtime(16, 0) <= t < dtime(20, 0):
        return {
            "is_open": False,
            "extended": True,
            "session": "after",
            "label": "After hours",
            "hint": "4:00 pm–8:00 pm ET · limit orders, extended hours",
        }
    return {
        "is_open": False,
        "extended": False,
        "session": "closed",
        "label": "Market closed",
        "hint": "Stocks next trade in regular hours, or 4:00 am–8:00 pm ET with a limit order",
    }


def money(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def snapshot(conn: Connection) -> dict:
    acct = alpaca.get_account(conn)
    positions = alpaca.get_positions(conn)
    clock = alpaca.get_clock(conn)
    equity = money(acct.get("equity"))
    last = money(acct.get("last_equity"))
    day_pl = equity - last
    return {
        "account": {
            "status": acct.get("status"),
            "account_number": str(acct.get("account_number") or ""),
            "equity": equity,
            "cash": money(acct.get("cash")),
            "buying_power": money(acct.get("buying_power")),
            "portfolio_value": money(acct.get("portfolio_value") or equity),
            "last_equity": last,
            "day_pl": day_pl,
            "day_plpc": (day_pl / last) if last else 0.0,
            "pattern_day_trader": bool(acct.get("pattern_day_trader")),
            "trading_blocked": bool(acct.get("trading_blocked")),
            "crypto_status": acct.get("crypto_status") or "",
            "options_status": (acct.get("options") or {}).get("status")
            if isinstance(acct.get("options"), dict)
            else acct.get("options_status") or "",
            "shorting_enabled": bool(acct.get("shorting_enabled")),
        },
        "clock": {
            "is_open": bool(clock.get("is_open")),
            **market_session(clock),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
            "timestamp": clock.get("timestamp"),
        },
        "positions": enrich_positions(conn, [normalize_position(p) for p in positions]),
        "paper": conn.paper,
    }


def normalize_position(p: dict) -> dict:
    qty = money(p.get("qty"))
    mv = money(p.get("market_value"))
    pl = money(p.get("unrealized_pl"))
    plpc = money(p.get("unrealized_plpc"))
    return {
        "symbol": p.get("symbol"),
        "qty": qty,
        "side": p.get("side"),
        "asset_class": p.get("asset_class") or "",
        "avg_entry": money(p.get("avg_entry_price")),
        "current_price": money(p.get("current_price")),
        "market_value": mv,
        "cost_basis": money(p.get("cost_basis")),
        "unrealized_pl": pl,
        "unrealized_plpc": plpc,
        "change_today": money(p.get("change_today")),
        "earnings": None,
        "dividend": None,
    }


def _is_stock_symbol(symbol: str, asset_class: str = "") -> bool:
    if not symbol or "/" in symbol or len(symbol) > 10:
        return False
    return asset_class not in {"crypto", "us_option", "option"}


def _parse_day(value: str) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _next_dividend(rows: list[dict], symbol: str, today: date) -> dict | None:
    upcoming = []
    for row in rows:
        if str(row.get("symbol") or "").upper() != symbol:
            continue
        ex_day = _parse_day(row.get("ex_date"))
        pay_day = _parse_day(row.get("payable_date"))
        mark = ex_day or pay_day
        if not mark or mark < today:
            continue
        upcoming.append((mark, row, ex_day, pay_day))
    if not upcoming:
        return None
    upcoming.sort(key=lambda item: item[0])
    _, row, ex_day, pay_day = upcoming[0]
    cash = money(row.get("cash"))
    return {
        "ex_date": ex_day.isoformat() if ex_day else "",
        "payable_date": pay_day.isoformat() if pay_day else "",
        "cash": cash,
        "days_to_ex": (ex_day - today).days if ex_day else None,
    }


def _yahoo_earnings(symbol: str) -> dict | None:
    import httpx

    try:
        with httpx.Client(timeout=4.0, headers={"User-Agent": "Cove/1.0"}) as client:
            r = client.get(
                f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                params={"modules": "calendarEvents"},
            )
        if r.status_code >= 400:
            return None
        result = (((r.json() or {}).get("quoteSummary") or {}).get("result") or [{}])[0]
        dates = (((result.get("calendarEvents") or {}).get("earnings") or {}).get("earningsDate") or [])
        today = date.today()
        parsed = []
        for item in dates:
            raw = item.get("fmt") if isinstance(item, dict) else None
            day = _parse_day(raw)
            if day:
                parsed.append(day)
        future = [d for d in parsed if d >= today]
        chosen = (future or parsed)
        if not chosen:
            return None
        day = chosen[0]
        return {"date": day.isoformat(), "days": (day - today).days}
    except Exception:
        return None


def enrich_positions(conn: Connection, positions: list[dict]) -> list[dict]:
    today = date.today()
    stocks = [p for p in positions if _is_stock_symbol(str(p.get("symbol") or ""), str(p.get("asset_class") or ""))]
    symbols = [str(p["symbol"]).upper() for p in stocks]
    div_rows: list[dict] = []
    if symbols:
        try:
            div_rows = alpaca.announcements_for_symbols(
                conn, symbols, today.isoformat(), (today + timedelta(days=90)).isoformat()
            )
        except AlpacaError:
            div_rows = []
    earn_map: dict[str, dict] = {}
    if symbols:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=6) as pool:
            for symbol, row in zip(symbols, pool.map(_yahoo_earnings, symbols)):
                if row:
                    earn_map[symbol] = row
    for pos in positions:
        symbol = str(pos.get("symbol") or "").upper()
        pos["dividend"] = _next_dividend(div_rows, symbol, today)
        if pos["dividend"]:
            pos["dividend"]["estimate"] = pos["dividend"]["cash"] * money(pos.get("qty"))
        pos["earnings"] = earn_map.get(symbol)
    return positions


def watchlist_rows(conn: Connection, symbols: list[str]) -> list[dict]:
    rows = []
    for symbol in symbols:
        name = symbol
        price = None
        change_pct = None
        closes: list[dict] = []
        try:
            if "/" in symbol:
                asset = {"name": symbol, "class": "crypto"}
                bars = alpaca.crypto_bars(conn, symbol, "180D")
            else:
                asset = alpaca.get_asset(conn, symbol)
                bars = alpaca.stock_bars(conn, symbol, "180D")
            name = str(asset.get("name") or symbol)
            for bar in bars:
                close = money(bar.get("c") or bar.get("close"))
                if close:
                    closes.append({"t": bar.get("t"), "c": close})
            if closes:
                price = closes[-1]["c"]
                first = closes[0]["c"]
                change_pct = ((price - first) / first) if first else 0.0
        except AlpacaError:
            pass
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "price": price,
                "change_pct": change_pct,
                "bars": closes,
            }
        )
    return rows


def _epoch_date(ts) -> date:
    n = int(float(ts))
    if n > 10_000_000_000:
        n //= 1000
    if n > 10_000_000_000:
        n //= 1000
    return datetime.fromtimestamp(n, tz=timezone.utc).date()


def _epoch_iso(ts) -> str:
    n = int(float(ts))
    if n > 10_000_000_000:
        n //= 1000
    if n > 10_000_000_000:
        n //= 1000
    return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()


def history_points(conn: Connection, period: str = "1M") -> dict:
    asked = period.upper()
    fetch = {"1Y": "1A", "1A": "1A", "YTD": "1A", "3Y": "all", "MAX": "all", "ALL": "all"}.get(asked, period)
    raw = alpaca.portfolio_history(conn, period=fetch, timeframe="1D" if fetch not in {"1D", "5D"} else "15Min")
    stamps = raw.get("timestamp") or []
    equity = [money(x) for x in (raw.get("equity") or [])]
    pl = [money(x) for x in (raw.get("profit_loss") or [])]
    points = []
    cutoff = None
    if asked == "YTD":
        cutoff = date(datetime.now(timezone.utc).year, 1, 1)
    elif asked == "3Y":
        cutoff = (datetime.now(timezone.utc) - timedelta(days=365 * 3)).date()
    for i, ts in enumerate(stamps):
        if i >= len(equity):
            break
        if str(ts).replace(".", "", 1).isdigit():
            iso = _epoch_iso(ts)
            day = _epoch_date(ts)
        else:
            iso = str(ts)
            day = datetime.fromisoformat(iso.replace("Z", "+00:00")).date()
        if cutoff and day < cutoff:
            continue
        points.append({"t": iso, "equity": equity[i], "pl": pl[i] if i < len(pl) else 0})
    return {"points": points, "base": money(raw.get("base_value")), "timeframe": raw.get("timeframe")}


def pnl_calendar(conn: Connection, year: int, month: int) -> dict:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    raw = alpaca.portfolio_history(conn, period="3M", timeframe="1D")
    stamps = raw.get("timestamp") or []
    pls = raw.get("profit_loss") or []
    by_day: dict[str, float] = {}
    for i, ts in enumerate(stamps):
        if str(ts).replace(".", "", 1).isdigit():
            d = _epoch_date(ts)
        else:
            d = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
        if start <= d <= end and i < len(pls):
            by_day[d.isoformat()] = by_day.get(d.isoformat(), 0) + money(pls[i])
    weeks: list[list[dict | None]] = []
    week: list[dict | None] = [None] * start.weekday()
    day = start
    while day <= end:
        key = day.isoformat()
        pl = by_day.get(key)
        week.append({"date": key, "day": day.day, "pl": pl, "has": pl is not None})
        if len(week) == 7:
            weeks.append(week)
            week = []
        day += timedelta(days=1)
    if week:
        week += [None] * (7 - len(week))
        weeks.append(week)
    return {
        "year": year,
        "month": month,
        "label": start.strftime("%B %Y"),
        "weeks": weeks,
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "sum": sum(v for v in by_day.values()),
    }


def dividend_events(conn: Connection, year: int, month: int) -> dict:
    start = date(year, month, 1)
    end = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
    positions = alpaca.get_positions(conn)
    symbols = []
    qty_map = {}
    for p in positions:
        sym = str(p.get("symbol") or "")
        if not sym or len(sym) > 10 or "/" in sym:
            continue
        symbols.append(sym)
        qty_map[sym] = money(p.get("qty"))
    events: list[dict] = []
    for symbol in symbols[:40]:
        rows = alpaca.announcements_for_symbol(conn, symbol, start.isoformat(), end.isoformat())
        for row in rows:
            cash = money(row.get("cash") or row.get("cash_amount") or row.get("rate"))
            events.append(
                {
                    "symbol": symbol,
                    "qty": qty_map.get(symbol, 0),
                    "estimate": cash * qty_map.get(symbol, 0),
                    "cash": cash,
                    "ex_date": str(row.get("ex_date") or "")[:10],
                    "record_date": str(row.get("record_date") or "")[:10],
                    "payable_date": str(row.get("payable_date") or "")[:10],
                    "declaration_date": str(row.get("declaration_date") or "")[:10],
                }
            )
    try:
        posted = alpaca.get_activities(conn, "DIV,DIVCGL,DIVCGS,DIVROC,DIVTXEX", page_size=50)
    except AlpacaError:
        posted = []
    history = []
    for act in posted:
        d = str(act.get("date") or act.get("transaction_time") or "")[:10]
        history.append(
            {
                "symbol": act.get("symbol"),
                "date": d,
                "net": money(act.get("net_amount")),
                "qty": money(act.get("qty")),
                "type": act.get("activity_type"),
            }
        )
    by_day: dict[str, list[dict]] = {}
    for ev in events:
        for key in ("ex_date", "payable_date"):
            d = ev.get(key) or ""
            if d.startswith(f"{year}-{month:02d}"):
                item = {**ev, "kind": "ex" if key == "ex_date" else "payable"}
                by_day.setdefault(d, []).append(item)
    weeks: list[list[dict | None]] = []
    week: list[dict | None] = [None] * start.weekday()
    day = start
    while day <= end:
        key = day.isoformat()
        week.append({"date": key, "day": day.day, "items": by_day.get(key, [])})
        if len(week) == 7:
            weeks.append(week)
            week = []
        day += timedelta(days=1)
    if week:
        week += [None] * (7 - len(week))
        weeks.append(week)
    return {
        "year": year,
        "month": month,
        "label": start.strftime("%B %Y"),
        "weeks": weeks,
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "upcoming": events,
        "posted": history,
    }


def build_order(body: dict) -> dict:
    asset = str(body.get("asset_class") or "us_equity")
    symbol = str(body.get("symbol") or "").upper().strip()
    side = str(body.get("side") or "buy").lower()
    order_type = str(body.get("type") or "market").lower()
    if not symbol:
        raise AlpacaError("Symbol is required")
    payload: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "client_order_id": str(body.get("client_order_id") or f"cove-{uuid.uuid4().hex[:20]}"),
    }
    qty = body.get("qty")
    notional = body.get("notional")
    if notional not in (None, "", 0, "0"):
        payload["notional"] = str(notional)
    elif qty not in (None, "", 0, "0"):
        payload["qty"] = str(qty)
    else:
        raise AlpacaError("Enter shares or a dollar amount")

    if asset == "crypto" or "/" in symbol:
        payload["time_in_force"] = str(body.get("time_in_force") or "gtc")
        if order_type == "limit":
            payload["limit_price"] = str(body.get("limit_price") or "")
        if order_type == "stop_limit":
            payload["stop_price"] = str(body.get("stop_price") or "")
            payload["limit_price"] = str(body.get("limit_price") or "")
        return payload

    if asset == "option" or len(symbol) > 12 or body.get("order_class") == "mleg":
        payload["time_in_force"] = "day"
        payload["position_intent"] = str(body.get("position_intent") or ("buy_to_open" if side == "buy" else "sell_to_close"))
        if order_type == "limit":
            payload["limit_price"] = str(body.get("limit_price") or "")
        if body.get("order_class") == "mleg":
            payload["order_class"] = "mleg"
            payload["legs"] = body.get("legs") or []
            payload.pop("symbol", None)
            payload.pop("side", None)
        return payload

    want_ext = bool(body.get("extended_hours"))
    tif = str(body.get("time_in_force") or "day").lower()
    if want_ext:
        if order_type != "limit":
            raise AlpacaError("Pre-market and after-hours need a limit order and a limit price. Alpaca will not take a market order outside regular hours.")
        tif = "day"
        payload["extended_hours"] = True
    if tif not in {"day", "gtc", "ioc", "fok", "opg", "cls"}:
        tif = "day"
    payload["time_in_force"] = tif
    if order_type in {"limit", "stop_limit"}:
        payload["limit_price"] = str(body.get("limit_price") or "")
    if order_type in {"stop", "stop_limit"}:
        payload["stop_price"] = str(body.get("stop_price") or "")
    if order_type == "trailing_stop":
        trail_pct = body.get("trail_percent")
        trail_px = body.get("trail_price") or body.get("stop_price")
        if trail_pct not in (None, "", 0, "0"):
            payload["trail_percent"] = str(trail_pct)
        elif trail_px not in (None, "", 0, "0"):
            payload["trail_price"] = str(trail_px)
        else:
            raise AlpacaError("Enter a trail amount")
    return payload


def option_chain_view(conn: Connection, underlying: str, expiration: str | None) -> dict:
    catalog = alpaca.option_contracts(conn, underlying, None, "call")
    expirations = sorted({str(c.get("expiration_date") or "")[:10] for c in catalog if c.get("expiration_date")})
    chosen = expiration or (expirations[0] if expirations else "")
    contracts = alpaca.option_contracts(conn, underlying, chosen) if chosen else []
    symbols = [str(c.get("symbol")) for c in contracts if c.get("symbol")]
    snaps = {}
    try:
        snaps = alpaca.option_snapshots(conn, symbols)
    except AlpacaError:
        snaps = {}
    by_strike: dict[float, dict] = {}
    for c in contracts:
        strike = money(c.get("strike_price"))
        row = by_strike.setdefault(strike, {"strike": strike, "call": None, "put": None})
        right = str(c.get("type") or c.get("option_type") or "").lower()
        snap = snaps.get(c.get("symbol")) or {}
        quote = snap.get("latestQuote") or snap.get("quote") or {}
        item = {
            "symbol": c.get("symbol"),
            "bid": money(quote.get("bp") or quote.get("bid_price")),
            "ask": money(quote.get("ap") or quote.get("ask_price")),
            "status": c.get("status"),
            "open_interest": c.get("open_interest"),
        }
        if "call" in right:
            row["call"] = item
        else:
            row["put"] = item
    rows = [by_strike[k] for k in sorted(by_strike)]
    return {"underlying": underlying.upper(), "expiration": chosen, "expirations": expirations, "rows": rows}
