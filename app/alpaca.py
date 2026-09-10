from __future__ import annotations

from typing import Any

import httpx

PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"
DATA = "https://data.alpaca.markets"


class AlpacaError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Alpaca:
    def __init__(
        self,
        *,
        paper: bool = True,
        api_key: str = "",
        secret: str = "",
        oauth_token: str = "",
    ):
        self.paper = paper
        self.trade_base = PAPER if paper else LIVE
        self.api_key = api_key
        self.secret = secret
        self.oauth_token = oauth_token

    def _headers(self) -> dict[str, str]:
        if self.oauth_token:
            return {"Authorization": f"Bearer {self.oauth_token}", "Accept": "application/json"}
        if not self.api_key or not self.secret:
            raise AlpacaError("Alpaca is not connected")
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret,
            "Accept": "application/json",
        }

    def _data_headers(self) -> dict[str, str]:
        # Market data accepts the same key/secret or OAuth as trading.
        return self._headers()

    def request(self, method: str, path: str, **kwargs) -> Any:
        url = path if path.startswith("http") else f"{self.trade_base}{path}"
        with httpx.Client(timeout=30.0) as client:
            r = client.request(method, url, headers=self._headers(), **kwargs)
        if r.status_code >= 400:
            detail = r.text[:800]
            raise AlpacaError(f"{r.status_code}: {detail}", status=r.status_code)
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    def data(self, path: str, params: dict | None = None) -> Any:
        url = path if path.startswith("http") else f"{DATA}{path}"
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, headers=self._data_headers(), params=params)
        if r.status_code >= 400:
            raise AlpacaError(f"{r.status_code}: {r.text[:800]}", status=r.status_code)
        return r.json()

    def account(self) -> dict:
        return self.request("GET", "/v2/account")

    def clock(self) -> dict:
        return self.request("GET", "/v2/clock")

    def positions(self) -> list[dict]:
        return self.request("GET", "/v2/positions") or []

    def orders(self, status: str = "all", limit: int = 50) -> list[dict]:
        return self.request("GET", "/v2/orders", params={"status": status, "limit": limit, "nested": True}) or []

    def activities(self, types: str = "FILL,DIV,DIVCGL,DIVCGS,CSD,CSW,OPEXP,OPASN,CFEE", page_size: int = 50) -> list[dict]:
        return self.request("GET", "/v2/account/activities", params={"activity_types": types, "page_size": page_size}) or []

    def portfolio_history(self, period: str = "1M", timeframe: str = "1D") -> dict:
        return self.request(
            "GET",
            "/v2/account/portfolio/history",
            params={"period": period, "timeframe": timeframe, "extended_hours": True},
        )

    def assets(self, q: str = "", asset_class: str | None = None) -> list[dict]:
        params: dict[str, str] = {"status": "active"}
        if asset_class:
            params["asset_class"] = asset_class
        rows = self.request("GET", "/v2/assets", params=params) or []
        needle = q.upper().strip()
        if not needle:
            return rows[:40]
        hits = [
            a
            for a in rows
            if needle in str(a.get("symbol", "")).upper() or needle in str(a.get("name", "")).upper()
        ]
        return hits[:40]

    def asset(self, symbol: str) -> dict:
        return self.request("GET", f"/v2/assets/{symbol}")

    def calendar(self, start: str, end: str) -> list[dict]:
        return self.request("GET", "/v2/calendar", params={"start": start, "end": end}) or []

    def submit_order(self, payload: dict) -> dict:
        return self.request("POST", "/v2/orders", json=payload)

    def cancel_order(self, order_id: str) -> None:
        self.request("DELETE", f"/v2/orders/{order_id}")

    def option_contracts(self, underlying: str, expiration_date: str | None = None, type_: str | None = None) -> list[dict]:
        from datetime import date, timedelta

        today = date.today()
        params: dict[str, str] = {
            "underlying_symbols": underlying.upper(),
            "status": "active",
            "limit": "1000",
            "expiration_date_gte": today.isoformat(),
        }
        if expiration_date:
            params["expiration_date"] = expiration_date
            params["expiration_date_gte"] = expiration_date
            params["expiration_date_lte"] = expiration_date
        else:
            params["expiration_date_lte"] = (today + timedelta(days=800)).isoformat()
        if type_:
            params["type"] = type_
        out: list[dict] = []
        token = None
        for _ in range(12):
            if token:
                params["page_token"] = token
            data = self.request("GET", "/v2/options/contracts", params=params) or {}
            if isinstance(data, list):
                out.extend(data)
                break
            out.extend(data.get("option_contracts") or [])
            token = data.get("next_page_token") or data.get("page_token")
            if not token:
                break
        return out

    def bars(self, symbol: str, timeframe: str = "1Day", limit: int = 300) -> list[dict]:
        from datetime import date, datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        ranges = {
            "YTD": ("1Day", date(now.year, 1, 1).isoformat(), 400),
            "180D": ("1Day", (now - timedelta(days=180)).date().isoformat(), 200),
            "1Y": ("1Day", (now - timedelta(days=365)).date().isoformat(), 400),
            "3Y": ("1Day", (now - timedelta(days=365 * 3)).date().isoformat(), 1200),
            "MAX": ("1Day", "1990-01-01", 4000),
        }
        lookback = {
            "1Min": (3, 500),
            "5Min": (10, 500),
            "15Min": (21, 500),
            "30Min": (30, 500),
            "1Hour": (90, 500),
            "4Hour": (240, 500),
            "1Day": (500, 400),
            "1Week": (1600, 400),
            "1Month": (3650, 400),
        }
        if timeframe in ranges:
            tf, start, limit = ranges[timeframe]
        else:
            days, limit = lookback.get(timeframe, (400, 300))
            tf = timeframe if timeframe in lookback else "1Day"
            start = (now - timedelta(days=days)).date().isoformat()
        sym = symbol.upper()
        if "/" in sym:
            return self._paged_bars(
                "/v1beta3/crypto/us/bars",
                sym,
                {"symbols": sym, "timeframe": tf, "start": start},
                limit,
            )
        if len(sym) > 15:
            return self._paged_bars(
                "/v1beta1/options/bars",
                sym,
                {"symbols": sym, "timeframe": tf, "start": start},
                limit,
            )
        return self._paged_bars(
            "/v2/stocks/bars",
            sym,
            {"symbols": sym, "timeframe": tf, "start": start, "adjustment": "split", "feed": "iex"},
            limit,
        )

    def _paged_bars(self, path: str, symbol: str, params: dict, limit: int) -> list[dict]:
        rows: list[dict] = []
        token = None
        while len(rows) < limit:
            q = {**params, "limit": min(1000, limit - len(rows))}
            if token:
                q["page_token"] = token
            data = self.data(path, params=q)
            chunk = (data.get("bars") or {}).get(symbol) or []
            if not chunk:
                break
            rows.extend(chunk)
            token = data.get("next_page_token")
            if not token:
                break
        return rows[-limit:]

    def snapshot(self, symbol: str) -> dict:
        sym = symbol.upper()
        if "/" in sym:
            data = self.data("/v1beta3/crypto/us/snapshots", params={"symbols": sym})
            return (data.get("snapshots") or {}).get(sym) or data
        try:
            data = self.data("/v2/stocks/snapshots", params={"symbols": sym, "feed": "iex"})
            return (data.get(sym) or data.get("snapshots", {}).get(sym) or data)
        except AlpacaError:
            return {}

    def latest_price(self, symbol: str) -> float | None:
        snap = self.snapshot(symbol)
        trade = snap.get("latestTrade") or snap.get("latest_trade") or {}
        quote = snap.get("latestQuote") or snap.get("latest_quote") or {}
        px = trade.get("p") or trade.get("price")
        if px is None:
            bp, ap = quote.get("bp"), quote.get("ap")
            if bp and ap:
                px = (float(bp) + float(ap)) / 2
        try:
            return float(px) if px is not None else None
        except (TypeError, ValueError):
            return None

    def news(self, symbol: str, limit: int = 8) -> list[dict]:
        try:
            data = self.data("/v1beta1/news", params={"symbols": symbol.upper(), "limit": limit})
            return data.get("news") or data.get("News") or []
        except AlpacaError:
            return []

    def corporate_actions(self, symbols: list[str], start: str, end: str) -> dict:
        if not symbols:
            return {}
        joined = ",".join(sorted({s.upper() for s in symbols}))
        try:
            return self.data(
                "/v1/corporate-actions",
                params={
                    "symbols": joined,
                    "types": "cash_dividend,stock_dividend,forward_split,reverse_split",
                    "start": start,
                    "end": end,
                    "limit": 1000,
                },
            )
        except AlpacaError:
            try:
                rows = self.request(
                    "GET",
                    "/v2/corporate_actions/announcements",
                    params={
                        "ca_types": "dividend,split",
                        "since": start,
                        "until": end,
                        "symbol": joined.split(",")[0],
                    },
                )
                return {"announcements": rows or []}
            except AlpacaError:
                return {}


def client_from_conn(conn) -> Alpaca:
    from app.entitlements import decrypt_str

    return Alpaca(
        paper=bool(getattr(conn, "paper", True)),
        api_key=decrypt_str(getattr(conn, "api_key_enc", None) or ""),
        secret=decrypt_str(getattr(conn, "secret_enc", None) or ""),
        oauth_token=decrypt_str(getattr(conn, "oauth_token_enc", None) or ""),
    )


def get_account(conn) -> dict:
    return client_from_conn(conn).account()


def get_positions(conn) -> list[dict]:
    return client_from_conn(conn).positions()


def get_clock(conn) -> dict:
    return client_from_conn(conn).clock()


def get_orders(conn, status: str = "all", limit: int = 50) -> list[dict]:
    return client_from_conn(conn).orders(status=status, limit=limit)


def get_activities(conn, types: str = "FILL,DIV,DIVCGL,DIVCGS,CSD,CSW,OPEXP,OPASN,CFEE", page_size: int = 50) -> list[dict]:
    return client_from_conn(conn).activities(types=types, page_size=page_size)


def portfolio_history(conn, period: str = "1M", timeframe: str = "1D") -> dict:
    return client_from_conn(conn).portfolio_history(period=period, timeframe=timeframe)


def get_asset(conn, symbol: str) -> dict:
    return client_from_conn(conn).asset(symbol)


def stock_bars(conn, symbol: str, timeframe: str = "1Day", limit: int = 300) -> list[dict]:
    return client_from_conn(conn).bars(symbol, timeframe=timeframe, limit=limit)


def crypto_bars(conn, symbol: str, timeframe: str = "1Day", limit: int = 300) -> list[dict]:
    return client_from_conn(conn).bars(symbol, timeframe=timeframe, limit=limit)


def latest_quote(conn, symbol: str) -> dict:
    snap = client_from_conn(conn).snapshot(symbol)
    if not isinstance(snap, dict):
        return {}
    return snap.get("latestQuote") or snap.get("latest_quote") or {}


def market_quote(conn, symbol: str) -> dict:
    snap = client_from_conn(conn).snapshot(symbol) if "/" not in symbol else {}
    if not isinstance(snap, dict):
        snap = {}
    quote = snap.get("latestQuote") or snap.get("latest_quote") or {}
    trade = snap.get("latestTrade") or snap.get("latest_trade") or {}
    prev = snap.get("prevDailyBar") or snap.get("prev_daily_bar") or {}
    daily = snap.get("dailyBar") or snap.get("daily_bar") or {}

    def num(*keys):
        for src in (trade, quote, daily, prev):
            for key in keys:
                if src.get(key) not in (None, ""):
                    try:
                        return float(src[key])
                    except (TypeError, ValueError):
                        pass
        return 0.0

    last = num("p", "c", "price")
    prev_c = 0.0
    try:
        prev_c = float(prev.get("c") or 0)
    except (TypeError, ValueError):
        prev_c = 0.0
    bid = num("bp", "bid_price")
    ask = num("ap", "ask_price")
    return {
        "bid": bid,
        "ask": ask,
        "bp": bid,
        "ap": ask,
        "last": last,
        "prev_close": prev_c,
        "change_pct": ((last - prev_c) / prev_c) if prev_c else 0.0,
        "asof": trade.get("t") or quote.get("t") or "",
    }


def news(conn, symbol: str, limit: int = 8) -> list[dict]:
    return client_from_conn(conn).news(symbol, limit=limit)


def submit_order(conn, payload: dict) -> dict:
    return client_from_conn(conn).submit_order(payload)


def cancel_order(conn, order_id: str) -> None:
    client_from_conn(conn).cancel_order(order_id)


def option_contracts(conn, underlying: str, expiration: str | None = None, type_: str | None = None) -> list[dict]:
    return client_from_conn(conn).option_contracts(underlying, expiration, type_)


def option_snapshots(conn, symbols: list[str]) -> dict:
    client = client_from_conn(conn)
    if not symbols:
        return {}
    snaps: dict = {}
    for i in range(0, len(symbols), 100):
        chunk = symbols[i : i + 100]
        data = client.data("/v1beta1/options/snapshots", params={"symbols": ",".join(chunk)})
        if not isinstance(data, dict):
            continue
        part = data.get("snapshots") or data
        if isinstance(part, dict):
            snaps.update(part)
    return snaps


def announcements_for_symbols(conn, symbols: list[str], start: str, end: str) -> list[dict]:
    rows: list[dict] = []
    if not symbols:
        return rows
    raw = client_from_conn(conn).corporate_actions(symbols, start, end)
    if not isinstance(raw, dict):
        return rows
    nested = raw.get("corporate_actions") if isinstance(raw.get("corporate_actions"), dict) else raw
    for key in ("cash_dividends", "stock_dividends", "announcements"):
        for item in nested.get(key) or raw.get(key) or []:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "symbol": str(item.get("symbol") or "").upper(),
                    "ex_date": str(item.get("ex_date") or item.get("ex_dividend_date") or "")[:10],
                    "record_date": str(item.get("record_date") or "")[:10],
                    "payable_date": str(item.get("payable_date") or "")[:10],
                    "declaration_date": str(item.get("declaration_date") or "")[:10],
                    "cash": item.get("cash") or item.get("rate") or item.get("cash_amount"),
                }
            )
    return rows


def announcements_for_symbol(conn, symbol: str, start: str, end: str) -> list[dict]:
    return announcements_for_symbols(conn, [symbol], start, end)


def oauth_authorize_url(state: str, env: str = "paper") -> str:
    from urllib.parse import urlencode

    from app.config import ALPACA_OAUTH_CLIENT_ID, ALPACA_OAUTH_REDIRECT_URI

    if not ALPACA_OAUTH_CLIENT_ID:
        raise AlpacaError("Alpaca Connect is not set up yet. Use API keys for now.")
    params = {
        "response_type": "code",
        "client_id": ALPACA_OAUTH_CLIENT_ID,
        "redirect_uri": ALPACA_OAUTH_REDIRECT_URI,
        "state": state,
        "scope": "account:write trading",
        "env": env,
    }
    return f"https://app.alpaca.markets/oauth/authorize?{urlencode(params)}"


def oauth_exchange(code: str) -> dict:
    from app.config import ALPACA_OAUTH_CLIENT_ID, ALPACA_OAUTH_CLIENT_SECRET, ALPACA_OAUTH_REDIRECT_URI

    if not ALPACA_OAUTH_CLIENT_ID or not ALPACA_OAUTH_CLIENT_SECRET:
        raise AlpacaError("Alpaca Connect is not set up yet.")
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            "https://api.alpaca.markets/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": ALPACA_OAUTH_CLIENT_ID,
                "client_secret": ALPACA_OAUTH_CLIENT_SECRET,
                "redirect_uri": ALPACA_OAUTH_REDIRECT_URI,
            },
        )
    if r.status_code >= 400:
        raise AlpacaError(f"{r.status_code}: {r.text[:800]}", status=r.status_code)
    return r.json()
