const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const money = (n, d = 2) => {
  const x = Number(n || 0);
  const sign = x < 0 ? "-" : "";
  return sign + "$" + Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
};
const pct = (n) => `${((Number(n) || 0) * 100).toFixed(2)}%`;
const clsPL = (n) => (Number(n) >= 0 ? "up" : "down");
const UP = "#22c55e";
const DOWN = "#ff3b30";

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({ ok: false, error: res.statusText }));
  if (!res.ok && !data.error) {
    const detail = data.detail;
    data.error = typeof detail === "string" ? detail : (Array.isArray(detail) ? detail.map((d) => d.msg || d).join(" ") : res.statusText);
  }
  return data;
}

function toast(msg, isErr) {
  let el = $("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.style.cssText = "position:fixed;bottom:18px;right:18px;padding:10px 14px;border-radius:10px;background:#222;z-index:9";
    document.body.appendChild(el);
  }
  el.textContent = isAlpacaKeyError(msg)
    ? "Alpaca rejected the API keys. Open Account and paste a new Paper key (PK…) and secret."
    : msg;
  el.style.color = isErr ? "#ff3b30" : "#ffd400";
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.textContent = ""), 4000);
}

function isAlpacaKeyError(err) {
  const s = String(err || "").toLowerCase();
  return s.includes("rejected the saved api") || s.includes("unauthorized") || /\b401\b/.test(s);
}

function showAlpacaError(mount, err) {
  const keyFail = isAlpacaKeyError(err);
  mount.innerHTML = `
    <div class="empty-desk">
      <h1>${keyFail ? "Alpaca keys need a refresh" : "Alpaca did not load"}</h1>
      <p>${keyFail
        ? "Alpaca rejected the keys saved in Cove. That usually means they were rotated, or Paper/Live does not match the key. This is not an Apple or Cove login error."
        : (err || "Could not reach Alpaca.")}</p>
      <p>On a computer open <b>app.alpaca.markets</b>, switch to <b>Paper</b>, open API Keys, then paste a key that starts with <b>PK</b> and its secret in Account.</p>
      <a class="btn primary" href="/account">Open Account</a>
    </div>`;
}

const CHART_TFS = [
  ["1m", "1Min"],
  ["5m", "5Min"],
  ["15m", "15Min"],
  ["1H", "1Hour"],
  ["1D", "1Day"],
  ["1W", "1Week"],
  ["1M", "1Month"],
];
const CHART_RANGES = [
  ["YTD", "YTD"],
  ["1Y", "1Y"],
  ["3Y", "3Y"],
  ["MAX", "MAX"],
];
const CHART_STYLES = [
  ["Candles", "candle"],
  ["Bars", "bar"],
  ["Line", "line"],
  ["Area", "area"],
];

function toUnix(t) {
  if (typeof t === "number") return t > 1e12 ? Math.floor(t / 1000) : Math.floor(t);
  const ms = Date.parse(t);
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

function normalizeBars(rows) {
  const out = [];
  for (const b of rows || []) {
    const time = typeof b.time === "number" ? b.time : toUnix(b.t || b.timestamp);
    const close = Number(b.c ?? b.close ?? b.vw ?? b.equity ?? b.value);
    if (!time || !Number.isFinite(close)) continue;
    const open = Number(b.o ?? b.open);
    const high = Number(b.h ?? b.high);
    const low = Number(b.l ?? b.low);
    out.push({
      time,
      open: Number.isFinite(open) ? open : close,
      high: Number.isFinite(high) ? Math.max(high, close) : close,
      low: Number.isFinite(low) ? Math.min(low, close) : close,
      close,
      volume: Number(b.v ?? b.volume ?? 0) || 0,
    });
  }
  out.sort((a, b) => a.time - b.time);
  const uniq = [];
  for (const row of out) {
    if (uniq.length && uniq[uniq.length - 1].time === row.time) uniq[uniq.length - 1] = row;
    else uniq.push(row);
  }
  return uniq;
}

function makeChart(host) {
  return LightweightCharts.createChart(host, {
    autoSize: true,
    layout: { background: { color: "#000000" }, textColor: "#fff8e1", fontFamily: "IBM Plex Sans, Segoe UI, sans-serif" },
    grid: { vertLines: { color: "#161616" }, horzLines: { color: "#161616" } },
    rightPriceScale: { borderColor: "#2b2b2b", visible: true, scaleMargins: { top: 0.08, bottom: 0.22 } },
    timeScale: { borderColor: "#2b2b2b", timeVisible: true, secondsVisible: false },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
    handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
  });
}

function PriceChart(host, ohlcEl) {
  this.host = host;
  this.ohlcEl = ohlcEl;
  this.chart = makeChart(host);
  this.series = null;
  this.volume = null;
  this.style = "candle";
  this.rows = [];
  this.chart.subscribeCrosshairMove((param) => this._paintOhlc(param));
  this._ro = new ResizeObserver(() => {
    this.chart.applyOptions({ width: host.clientWidth, height: host.clientHeight });
  });
  this._ro.observe(host);
}

PriceChart.prototype.destroy = function () {
  this._ro?.disconnect();
  this.chart.remove();
};

PriceChart.prototype.setStyle = function (style) {
  this.style = style;
  this._apply();
};

PriceChart.prototype.setBars = function (rows) {
  this.rows = normalizeBars(rows);
  this._apply();
  const w = this.host.clientWidth;
  const h = this.host.clientHeight;
  if (w && h) this.chart.applyOptions({ width: w, height: h });
  this.chart.timeScale().fitContent();
};

PriceChart.prototype._apply = function () {
  if (this.series) this.chart.removeSeries(this.series);
  if (this.volume) this.chart.removeSeries(this.volume);
  const common = {
    lastValueVisible: true,
    priceLineVisible: true,
    priceFormat: { type: "price", precision: 2, minMove: 0.01 },
  };
  if (this.style === "bar") {
    this.series = this.chart.addBarSeries({ ...common, upColor: UP, downColor: DOWN });
    this.series.setData(this.rows);
  } else if (this.style === "line") {
    this.series = this.chart.addLineSeries({ ...common, color: UP, lineWidth: 2 });
    this.series.setData(this.rows.map((r) => ({ time: r.time, value: r.close })));
  } else if (this.style === "area") {
    this.series = this.chart.addAreaSeries({
      ...common,
      lineColor: UP,
      topColor: "rgba(34,197,94,0.28)",
      bottomColor: "rgba(34,197,94,0.02)",
      lineWidth: 2,
    });
    this.series.setData(this.rows.map((r) => ({ time: r.time, value: r.close })));
  } else {
    this.series = this.chart.addCandlestickSeries({
      ...common,
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
    });
    this.series.setData(this.rows);
  }
  this.volume = this.chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "vol",
    lastValueVisible: false,
    priceLineVisible: false,
  });
  this.chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, borderVisible: false });
  this.volume.setData(
    this.rows.map((r) => ({
      time: r.time,
      value: r.volume,
      color: r.close >= r.open ? "rgba(34,197,94,0.35)" : "rgba(255,59,48,0.35)",
    }))
  );
  this._paintOhlc();
};

PriceChart.prototype.last = function () {
  return this.rows[this.rows.length - 1] || null;
};

PriceChart.prototype._paintOhlc = function (param) {
  if (!this.ohlcEl) return;
  let row = this.last();
  if (param && param.time && this.series) {
    const raw = param.seriesData.get(this.series);
    if (raw) {
      row = {
        open: raw.open ?? raw.value,
        high: raw.high ?? raw.value,
        low: raw.low ?? raw.value,
        close: raw.close ?? raw.value,
      };
    }
  }
  if (!row) {
    this.ohlcEl.textContent = "";
    return;
  }
  this.ohlcEl.innerHTML = `O <b>${Number(row.open).toFixed(2)}</b> H <b>${Number(row.high).toFixed(2)}</b> L <b>${Number(row.low).toFixed(2)}</b> C <b>${Number(row.close).toFixed(2)}</b>`;
};

function chartToolbar(tf, style) {
  return `
    <div class="chart-tools">
      <div class="seg">${CHART_TFS.map(([label, value]) => `<button class="btn" data-tf="${value}" ${value === tf ? 'aria-pressed="true"' : ""}>${label}</button>`).join("")}</div>
      <div class="seg">${CHART_STYLES.map(([label, value]) => `<button class="btn" data-style="${value}" ${value === style ? 'aria-pressed="true"' : ""}>${label}</button>`).join("")}</div>
    </div>
    <div class="chart-tools">
      <div class="seg">${CHART_RANGES.map(([label, value]) => `<button class="btn" data-tf="${value}">${label}</button>`).join("")}</div>
    </div>`;
}

function needLink(connection, mount) {
  if (connection?.linked) return false;
  mount.innerHTML = `
    <div class="empty-desk">
      <img class="brand-mark xl" src="/static/img/alpaca-cove-icon.png" alt="Alpaca Cove">
      <h1>Welcome to the cove</h1>
      <p>Link your Alpaca account in <a href="/account">Account</a> to load balances, place trades, and fill the calendars. This app is only an interface. Trades stay on Alpaca. We never hold your money.</p>
      <a class="btn primary" href="/account">Link Alpaca</a>
    </div>`;
  return true;
}

async function boot() {
  const page = document.body.dataset.page;
  const needsCharts = ["home", "trade", "watchlist", "options", "calendar"].includes(page);
  if (needsCharts && !window.LightweightCharts) {
    document.getElementById("view").innerHTML = `<div class="notice">Charts did not load. Close the app and open it again.</div>`;
    return;
  }
  const me = await api("/api/me");
  if (!me.ok) {
    const root = document.getElementById("view");
    if (root) {
      root.innerHTML = `<div class="notice">${me.error || "Sign in required."} <a href="/login">Sign in</a></div>`;
    }
    return;
  }
  window.COVE = me;
  startAlertWatch();
  if (page === "home") return home(me);
  if (page === "trade") return trade(me);
  if (page === "watchlist") return watchlist(me);
  if (page === "options") return options(me);
  if (page === "calendar") return calendar(me);
  if (page === "dividends") return dividends(me);
  if (page === "activity") return activity(me);
  if (page === "alerts") return alerts(me);
  if (page === "account") return account(me);
  if (page === "upgrade") return upgrade(me);
  if (page === "share") return share(me);
  if (page === "feedback") return feedback();
  if (page === "readme") return readme(me);
  if (page === "more") return more(me);
}

function startAlertWatch() {
  if (window._coveAlertWatch) return;
  window._coveAlertWatch = true;
  if (window.Notification && Notification.permission === "default") {
    Notification.requestPermission().catch(() => {});
  }
  const seenKey = "cove-seen-alert";
  const tick = async () => {
    const data = await api("/api/alerts");
    if (!data.ok) return;
    const notes = data.notifications || [];
    const newest = notes[0];
    if (!newest) return;
    const last = sessionStorage.getItem(seenKey);
    if (!last) {
      sessionStorage.setItem(seenKey, String(newest.id));
      return;
    }
    if (String(newest.id) === last) return;
    sessionStorage.setItem(seenKey, String(newest.id));
    toast(newest.title);
    if (window.Notification && Notification.permission === "granted") {
      try {
        new Notification(newest.title, { body: newest.body || "Open Alerts in Alpaca Cove.", icon: "/static/img/alpaca-cove-icon.png" });
      } catch {}
    }
  };
  setTimeout(tick, 1500);
  setInterval(tick, 45000);
}

async function home(me) {
  const root = $("#view");
  if (needLink(me.connection, root)) return;
  const snap = await api("/api/snapshot");
  if (!snap.ok) return showAlpacaError(root, snap.error);
  const hist = await api("/api/history?period=1M");
  const a = snap.account;
  root.innerHTML = `
    <div class="desk-hero">
      <img class="brand-mark lg" src="/static/img/alpaca-cove-icon.png" alt="">
      <div>
        <div class="muted">${snap.clock?.label || (snap.clock?.is_open ? "Market open" : "Market closed")} · ${snap.paper ? "Paper" : "Live"}</div>
        <p class="kpi ${clsPL(a.day_pl)}">${money(a.equity)}</p>
        <p class="${clsPL(a.day_pl)}">${money(a.day_pl)} (${pct(a.day_plpc)}) today</p>
      </div>
    </div>
    <div class="row" style="margin-top:8px">
      <div></div>
      <div class="seg">${[["1D","1D"],["1W","1W"],["1M","1M"],["3M","3M"],["YTD","YTD"],["1Y","1Y"],["3Y","3Y"],["MAX","MAX"]].map(([label,p]) => `<button class="btn" data-p="${p}" ${p==="1M" ? 'aria-pressed="true"' : ""}>${label}</button>`).join("")}</div>
    </div>
    <div class="chart-wrap"><div class="chart-box"><div class="chart-ohlc" id="eq-ohlc"></div><div class="chart-mount" id="eq-box"></div></div></div>
    <div class="metrics">
      <div class="metric"><span>Cash</span><b>${money(a.cash)}</b></div>
      <div class="metric"><span>Buying power</span><b>${money(a.buying_power)}</b></div>
      <div class="metric"><span>Positions</span><b>${snap.positions.length}</b></div>
      <div class="metric"><span>PDT</span><b>${a.pattern_day_trader ? "Yes" : "No"}</b></div>
    </div>
    <h3>Positions</h3>
    <div class="table-wrap"><table><thead><tr>
      <th>Symbol</th><th>Qty</th><th>Avg</th><th>Price</th><th>Value</th><th>P&L</th><th>Earnings</th><th>Dividend</th>
    </tr></thead>
    <tbody>${snap.positions.map(p => `<tr>
      <td><a href="/trade?symbol=${encodeURIComponent(p.symbol)}">${p.symbol}</a></td>
      <td>${p.qty}</td>
      <td>${money(p.avg_entry)}</td>
      <td>${money(p.current_price)}</td>
      <td>${money(p.market_value)}</td>
      <td class="${clsPL(p.unrealized_pl)}">${money(p.unrealized_pl)} (${pct(p.unrealized_plpc)})</td>
      <td>${p.earnings ? `${p.earnings.days}d<div class="sub">${p.earnings.date}</div>` : `<span class="muted">—</span>`}</td>
      <td>${p.dividend ? `Ex ${p.dividend.ex_date || "—"}${p.dividend.cash ? ` · ${money(p.dividend.cash)}` : ""}${p.dividend.estimate ? `<div class="sub">Est ${money(p.dividend.estimate)}</div>` : ""}` : `<span class="muted">—</span>`}</td>
    </tr>`).join("") || `<tr><td colspan="8" class="muted">No open positions.</td></tr>`}</tbody></table></div>`;
  const equityChart = new PriceChart($("#eq-box"), $("#eq-ohlc"));
  equityChart.setStyle("area");
  equityChart.setBars((hist.points || []).map((p) => ({ t: p.t, c: p.equity, o: p.equity, h: p.equity, l: p.equity, v: 0 })));
  $$("[data-p]").forEach((b) => b.addEventListener("click", async () => {
    $$("[data-p]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    const h = await api("/api/history?period=" + b.dataset.p);
    equityChart.setBars((h.points || []).map((p) => ({ t: p.t, c: p.equity, o: p.equity, h: p.equity, l: p.equity, v: 0 })));
  }));
}

async function trade(me) {
  const root = $("#view");
  const params = new URLSearchParams(location.search);
  const pre = params.get("symbol") || "AAPL";
  root.innerHTML = `
    <div class="ticket">
      <div>
        <label>Symbol</label>
        <input id="sym" value="${pre}" />
        <button class="btn" id="load">Load</button>
        <p class="chart-price" id="lastpx"></p>
        ${chartToolbar("1Day", "candle")}
        <div class="chart-wrap"><div class="chart-box"><div class="chart-ohlc" id="eq-ohlc"></div><div class="chart-mount" id="eq-box"></div></div></div>
        <div id="meta"></div>
        <div id="news"></div>
      </div>
      <div class="card order-card">
        ${me.entitlement?.can_trade ? "" : `<p class="warn">Trial ended. Subscribe in Account to place orders.</p>`}
        <div class="search-row">
          <input id="osym" placeholder="Search symbol" value="${pre}" autocomplete="off" />
        </div>
        <div class="order-head">
          <div>
            <div class="ticker" id="oticker">${pre}</div>
            <div class="muted" id="oname">—</div>
          </div>
          <div class="head-px">
            <div class="last" id="olast">—</div>
            <div class="muted" id="ochg">—</div>
          </div>
        </div>
        <div class="ba">
          <div>Bid <b class="up" id="obid">—</b></div>
          <div>Ask <b class="down" id="oask">—</b></div>
        </div>
        <p class="muted" id="sess">Checking Alpaca session…</p>
        <div class="quote-meta">
          <span>IEX quote</span>
          <span id="oasof">—</span>
          <button class="btn" type="button" id="qref">Refresh</button>
        </div>
        <div class="seg">
          <button class="btn" data-side="buy" aria-pressed="true">Buy</button>
          <button class="btn" data-side="sell">Sell</button>
        </div>
        <div class="qty-row">
          <label>Quantity</label>
          <div class="seg unit">
            <button class="btn" data-unit="shares" aria-pressed="true">#</button>
            <button class="btn" data-unit="dollars">$</button>
          </div>
        </div>
        <input id="qty" value="1" />
        <label>Order type</label>
        <select id="type">
          <option value="market">Market</option>
          <option value="limit">Limit</option>
          <option value="stop">Stop</option>
          <option value="stop_limit">Stop limit</option>
          <option value="trailing_stop">Trailing stop</option>
        </select>
        <div id="limit-wrap" hidden>
          <label>Limit price</label>
          <input id="limitpx" placeholder="0.00" />
        </div>
        <div id="stop-wrap" hidden>
          <label>Stop price</label>
          <input id="stoppx" placeholder="0.00" />
        </div>
        <div id="trail-wrap" hidden>
          <label>Trail amount</label>
          <div class="qty-row">
            <input id="trail" placeholder="1.00" />
            <div class="seg unit">
              <button class="btn" data-trail="price" aria-pressed="true">$</button>
              <button class="btn" data-trail="percent">%</button>
            </div>
          </div>
        </div>
        <label>Time in force</label>
        <select id="tif">
          <option value="day">DAY — expires 4:00 pm ET</option>
          <option value="gtc">GTC — expires in 90 days</option>
          <option value="fok">FOK — fill or kill</option>
          <option value="ioc">IOC — immediate or cancel</option>
          <option value="opg">OPG — at the open</option>
          <option value="cls">CLS — at the close</option>
        </select>
        <label class="chk" id="ext-row">
          <input type="checkbox" id="ext">
          <span>Pre-market / after-hours<br><span class="muted">Alpaca 4:00 am–8:00 pm ET. Must be a limit order.</span></span>
        </label>
        <p class="muted" id="ext-hint" hidden>This will send a DAY limit order with extended hours on, so Alpaca can fill it before 9:30 am or after 4:00 pm ET.</p>
        <button class="btn primary wide" id="send" ${me.entitlement?.can_trade ? "" : "disabled"}>Review & send</button>
        <p class="muted" id="tstatus"></p>
      </div>
    </div>`;
  let side = "buy";
  let tf = "1Day";
  let style = "candle";
  let unit = "shares";
  let trailKind = "price";
  const priceChart = new PriceChart($("#eq-box"), $("#eq-ohlc"));
  $$("[data-side]").forEach((b) => b.onclick = () => {
    side = b.dataset.side;
    $$("[data-side]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  });
  $$("[data-tf]").forEach((b) => b.onclick = () => {
    tf = b.dataset.tf;
    $$("[data-tf]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    loadBars();
  });
  $$("[data-style]").forEach((b) => b.onclick = () => {
    style = b.dataset.style;
    $$("[data-style]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    priceChart.setStyle(style);
  });
  $$("[data-unit]").forEach((b) => b.onclick = () => {
    unit = b.dataset.unit;
    $$("[data-unit]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    $("#qty").placeholder = unit === "dollars" ? "50" : "1";
  });
  $$("[data-trail]").forEach((b) => b.onclick = () => {
    trailKind = b.dataset.trail;
    $$("[data-trail]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  });
  function applyExtendedHours() {
    const on = $("#ext").checked;
    $("#ext-hint").hidden = !on;
    if (!on) return;
    $("#type").value = "limit";
    $("#tif").value = "day";
    $("#limit-wrap").hidden = false;
    const ask = Number(String($("#oask").textContent || "").replace(/[^0-9.]/g, ""));
    const bid = Number(String($("#obid").textContent || "").replace(/[^0-9.]/g, ""));
    const last = Number(String($("#olast").textContent || "").replace(/[^0-9.]/g, ""));
    if (!$("#limitpx").value) {
      const px = side === "buy" ? (ask || last) : (bid || last);
      if (px) $("#limitpx").value = px.toFixed(2);
    }
  }
  function syncTypeFields() {
    const t = $("#type").value;
    $("#limit-wrap").hidden = !["limit", "stop_limit"].includes(t);
    $("#stop-wrap").hidden = !["stop", "stop_limit"].includes(t);
    $("#trail-wrap").hidden = t !== "trailing_stop";
    if ($("#ext").checked && t !== "limit") {
      toast("Pre-market and after-hours only work as a limit order.", true);
      $("#type").value = "limit";
      $("#limit-wrap").hidden = false;
    }
    if ($("#ext").checked && $("#tif").value !== "day") {
      $("#tif").value = "day";
    }
  }
  $("#type").onchange = syncTypeFields;
  $("#tif").onchange = syncTypeFields;
  $("#ext").onchange = applyExtendedHours;
  syncTypeFields();
  async function loadBars() {
    const symbol = $("#sym").value.trim().toUpperCase();
    const bars = await api("/api/bars?symbol=" + encodeURIComponent(symbol) + "&timeframe=" + encodeURIComponent(tf));
    if (!bars.ok) return toast(bars.error, true);
    priceChart.setStyle(style);
    priceChart.setBars(bars.bars || []);
    const last = priceChart.last();
    if (last) $("#lastpx").textContent = money(last.close);
    else $("#lastpx").textContent = "";
  }
  function paintQuote(symbol, data) {
    const q = data.quote || {};
    const last = q.last || priceChart.last()?.close;
    const chg = Number(q.change_pct || 0);
    $("#oticker").textContent = symbol;
    $("#oname").textContent = data.asset?.name || data.asset?.class || "";
    $("#olast").textContent = last ? money(last) : "—";
    $("#ochg").textContent = (chg >= 0 ? "+" : "") + (chg * 100).toFixed(2) + "%";
    $("#ochg").className = clsPL(chg);
    $("#obid").textContent = q.bid ? Number(q.bid).toFixed(2) : "—";
    $("#oask").textContent = q.ask ? Number(q.ask).toFixed(2) : "—";
    $("#oasof").textContent = (q.asof || "").toString().replace("T", " ").slice(0, 19) || "—";
    if (last) $("#lastpx").textContent = money(last);
  }
  async function load(fromEl) {
    const typed = (fromEl?.value || "").trim();
    const symbol = (typed || $("#sym").value || $("#osym").value || "").trim().toUpperCase();
    if (!symbol) return toast("Type a symbol first.", true);
    $("#sym").value = symbol;
    $("#osym").value = symbol;
    const data = await api("/api/asset?symbol=" + encodeURIComponent(symbol));
    if (!data.ok) return toast(data.error, true);
    await loadBars();
    paintQuote(symbol, data);
    $("#meta").innerHTML = `<p>${data.asset?.name || symbol} · ${data.asset?.class || data.asset?.asset_class || ""}</p>
      <button class="btn" id="watch">Add to watchlist</button>
      <button class="btn" id="alert">Price alert</button>
      <div id="alert-box" hidden class="card" style="margin-top:12px">
        <label>Alert when ${symbol} crosses</label>
        <input id="alertpx" inputmode="decimal" placeholder="Price" />
        <div class="seg">
          <button class="btn" type="button" data-aop="above" aria-pressed="true">Above</button>
          <button class="btn" type="button" data-aop="below">Below</button>
        </div>
        <button class="btn primary wide" type="button" id="alertsave">Save alert</button>
      </div>`;
    $("#news").innerHTML = (data.news || []).slice(0, 5).map((n) => `<div class="list-item"><a href="${n.url || "#"}" target="_blank">${n.headline || n.title}</a></div>`).join("");
    $("#watch")?.addEventListener("click", async () => {
      const out = await api("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol }) });
      toast(out.ok ? "Watching " + symbol : (out.error || "Could not save"), !out.ok);
    });
    let aop = "above";
    $("#alert")?.addEventListener("click", () => {
      const box = $("#alert-box");
      box.hidden = !box.hidden;
    });
    $$("[data-aop]").forEach((b) => b.onclick = () => {
      aop = b.dataset.aop;
      $$("[data-aop]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    });
    $("#alertsave")?.addEventListener("click", async () => {
      const price = Number($("#alertpx").value);
      if (!price) return toast("Enter a price", true);
      const out = await api("/api/alerts", { method: "POST", body: JSON.stringify({ symbol, op: aop, price }) });
      toast(out.ok ? "Alert saved" : (out.error || "Could not save"), !out.ok);
      if (out.ok) $("#alert-box").hidden = true;
    });
  }
  $("#load").onclick = () => load($("#sym"));
  $("#qref").onclick = () => load($("#osym"));
  $("#sym").addEventListener("keydown", (e) => {
    if (e.key === "Enter") load($("#sym"));
  });
  $("#osym").addEventListener("keydown", (e) => {
    if (e.key === "Enter") load($("#osym"));
  });
  $("#send").onclick = async () => {
    if ($("#ext").checked) applyExtendedHours();
    const t = $("#type").value;
    const qtyVal = $("#qty").value;
    if ($("#ext").checked && t !== "limit") {
      return toast("Pre-market and after-hours need a limit order.", true);
    }
    if ($("#ext").checked && !Number($("#limitpx").value)) {
      return toast("Enter a limit price for extended hours.", true);
    }
    const body = {
      symbol: $("#sym").value.trim(),
      side,
      type: t,
      qty: unit === "shares" ? qtyVal : null,
      notional: unit === "dollars" ? qtyVal : null,
      limit_price: $("#limitpx")?.value || null,
      stop_price: $("#stoppx")?.value || null,
      trail_price: t === "trailing_stop" && trailKind === "price" ? $("#trail").value : null,
      trail_percent: t === "trailing_stop" && trailKind === "percent" ? $("#trail").value : null,
      time_in_force: $("#tif").value,
      extended_hours: $("#ext").checked,
      asset_class: $("#sym").value.includes("/") ? "crypto" : "us_equity",
    };
    const summary = [
      side.toUpperCase(),
      unit === "dollars" ? money(qtyVal) : (qtyVal + " sh"),
      body.symbol,
      t.replace("_", " "),
      $("#tif").value.toUpperCase(),
      body.extended_hours ? "EXTENDED HOURS" : "",
    ].filter(Boolean).join(" ");
    if (!confirm("Send " + summary + "?")) return;
    const out = await api("/api/orders", { method: "POST", body: JSON.stringify(body) });
    $("#tstatus").textContent = out.ok ? `Submitted ${out.order?.id || ""}` : out.error;
    toast(out.ok ? "Order sent" : out.error, !out.ok);
  };
  const clockSnap = await api("/api/snapshot");
  if (clockSnap.ok && clockSnap.clock) {
    const c = clockSnap.clock;
    $("#sess").textContent = `${c.label || "Session"} · ${c.hint || ""}`;
    if (c.extended && !$("#ext").checked) {
      $("#ext").checked = true;
      applyExtendedHours();
    }
  } else {
    $("#sess").textContent = "Tick pre-market / after-hours to send a limit order outside 9:30 am–4:00 pm ET.";
  }
  load();
}

function sparkSVG(bars) {
  const vals = (bars || []).map((b) => Number(b.c)).filter((n) => Number.isFinite(n));
  if (vals.length < 2) return `<span class="muted">—</span>`;
  const w = 168, h = 44;
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const path = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * w;
    const y = h - ((v - min) / span) * (h - 6) - 3;
    return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path d="${path}" fill="none" stroke="${up ? UP : DOWN}" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

async function watchlist(me) {
  const root = $("#view");
  async function draw() {
    const data = await api("/api/watchlist");
    root.innerHTML = `
      <div class="row">
        <h1 class="page">Watchlist</h1>
        <div class="watch-add">
          <input id="wsym" placeholder="Add symbol" style="max-width:160px" />
          <button class="btn primary" id="wadd">Add</button>
        </div>
      </div>
      ${data.linked ? "" : `<p class="notice">Link Alpaca in Account to load names, prices, and 180-day trends.</p>`}
      <div class="watch-list">
        ${(data.items || []).map((item) => `
          <a class="watch-row" href="/trade?symbol=${encodeURIComponent(item.symbol)}">
            <div>
              <div class="ticker">${item.symbol}</div>
              <div class="muted">${item.name || ""}</div>
            </div>
            <div class="watch-px">
              <div class="last">${item.price != null ? money(item.price) : "—"}</div>
              <div class="${item.change_pct == null ? "muted" : clsPL(item.change_pct)}">${item.change_pct == null ? "" : (item.change_pct >= 0 ? "+" : "") + (item.change_pct * 100).toFixed(2) + "% · 180d"}</div>
            </div>
            <div class="watch-spark">${sparkSVG(item.bars)}</div>
            <button class="btn" data-del="${item.symbol}" type="button">Remove</button>
          </a>`).join("") || `<p class="muted">Nothing saved yet. Add a symbol here, or tap Add to watchlist on Trade.</p>`}
      </div>`;
    $("#wadd").onclick = async () => {
      const symbol = $("#wsym").value.trim().toUpperCase();
      if (!symbol) return;
      const out = await api("/api/watchlist", { method: "POST", body: JSON.stringify({ symbol }) });
      if (!out.ok) return toast(out.error || "Could not save that symbol", true);
      draw();
    };
    $("#wsym").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#wadd").click(); });
    $$("[data-del]").forEach((b) => b.onclick = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      await api("/api/watchlist/" + b.dataset.del, { method: "DELETE" });
      draw();
    });
  }
  draw();
}

function payoffSVG(kind) {
  const maps = {
    long_call: "M10,50 H70 L150,12",
    covered_call: "M10,68 L80,20 H150",
    long_put: "M10,12 L90,50 H150",
    csp: "M10,68 L80,20 H150",
    call_debit: "M10,52 H50 L110,18 H150",
    call_credit: "M10,22 H50 L110,56 H150",
    put_debit: "M10,22 H50 L110,56 H150",
    put_credit: "M10,52 H50 L110,18 H150",
  };
  const bull = !["long_put", "call_credit", "put_debit"].includes(kind);
  const fill = bull ? "rgba(46,204,113,0.22)" : "rgba(255,59,48,0.22)";
  const stroke = bull ? "#2ecc71" : "#ff3b30";
  const d = maps[kind] || maps.long_call;
  return `<svg class="payoff" viewBox="0 0 160 80">
    <line x1="8" y1="40" x2="152" y2="40" stroke="#3a3a3a" stroke-dasharray="3 3"/>
    <path d="${d} V40 H10 Z" fill="${fill}"/>
    <path d="${d}" fill="none" stroke="${stroke}" stroke-width="2"/>
  </svg>`;
}

async function options(me) {
  const root = $("#view");
  if (needLink(me.connection, root)) return;
  const canTrade = !!me.entitlement?.can_trade;
  const singles = [
    { id: "long_call", name: "Long Call", bias: "Bullish", side: "buy", right: "call", width: 0 },
    { id: "covered_call", name: "Covered Call", bias: "Bullish", side: "sell", right: "call", width: 0 },
    { id: "long_put", name: "Long Put", bias: "Bearish", side: "buy", right: "put", width: 0 },
    { id: "csp", name: "Cash-Secured Put", bias: "Bullish", side: "sell", right: "put", width: 0 },
  ];
  const verticals = [
    { id: "call_debit", name: "Call Debit Spread", bias: "Bullish", side: "buy", right: "call", width: 1 },
    { id: "call_credit", name: "Call Credit Spread", bias: "Bearish", side: "sell", right: "call", width: 1 },
    { id: "put_debit", name: "Put Debit Spread", bias: "Bearish", side: "buy", right: "put", width: 1 },
    { id: "put_credit", name: "Put Credit Spread", bias: "Bullish", side: "sell", right: "put", width: 1 },
  ];
  const widths = [["Single","0"],["1","1"],["2","2"],["3","3"],["4","4"],["5","5"],["7","7"],["10","10"],["15","15"],["20","20"]];
  root.innerHTML = `
    <div class="row">
      <div class="watch-add">
        <input id="und" value="AAPL" style="max-width:160px" />
        <button class="btn primary" id="oload">Load</button>
      </div>
      <button class="tab-pill" id="builder-btn" type="button"><span class="builder-ico"></span>Builder</button>
    </div>
    <p class="muted" id="ounder">—</p>
    <section id="builder-panel" hidden>
      <div class="opt-block">
        <h2 class="opt-h">Single leg</h2>
        <p class="muted">Tap a card. Alpaca Cove fills Buy/Sell, Call/Put, and width, then builds the legs.</p>
        <div class="strat-grid">${singles.map((s) => `
          <button class="strat-card" data-strat="${s.id}">
            ${payoffSVG(s.id)}
            <b>${s.name}</b>
            <span class="muted">${s.bias}</span>
          </button>`).join("")}</div>
      </div>
      <div class="opt-block">
        <h2 class="opt-h">Vertical spreads</h2>
        <p class="muted">Two strikes of the same type. Width is how many listed strikes apart.</p>
        <div class="strat-grid">${verticals.map((s) => `
          <button class="strat-card" data-strat="${s.id}">
            ${payoffSVG(s.id)}
            <b>${s.name}</b>
            <span class="muted">${s.bias}</span>
          </button>`).join("")}</div>
      </div>
    </section>
    <div class="opt-desk">
      <div class="card opt-controls">
        <div class="opt-pick">
          <div>
            <label>Buy / Sell</label>
            <div class="seg">
              <button class="btn" data-oside="buy" aria-pressed="true">Buy</button>
              <button class="btn" data-oside="sell">Sell</button>
            </div>
          </div>
          <div>
            <label>Call / Put</label>
            <div class="seg">
              <button class="btn" data-oright="call" aria-pressed="true">Call</button>
              <button class="btn" data-oright="put">Put</button>
            </div>
          </div>
          <div>
            <label>Contracts</label>
            <input id="oqty" value="1" />
          </div>
          <div>
            <label>Limit (optional)</label>
            <input id="olimit" placeholder="Debit / credit" />
          </div>
        </div>
        <label>Expiration</label>
        <select id="olength"></select>
        <div id="exps" class="exp-rail"></div>
        <label>Strike width</label>
        <div class="seg wrap" id="owidths">
          ${widths.map(([l,v],i) => `<button class="btn" data-owidth="${v}" ${i===0?'aria-pressed="true"':""}>${l}</button>`).join("")}
        </div>
        <div class="opt-pick">
          <div>
            <label>Anchor strike</label>
            <select id="ostrike"></select>
          </div>
          <div>
            <label>Second strike</label>
            <input id="ofar" value="—" disabled />
          </div>
        </div>
      </div>
      <div class="card" id="opreview">${payoffSVG("long_call")}<b>Long Call</b><p class="muted">Bullish · single leg</p><p class="muted" id="olegs">Load a symbol. Alpaca Cove will build the legs from your picks.</p>
        <div class="opt-risk">
          <div><span>Debit / Credit</span><b>—</b></div>
          <div><span>Max win</span><b>—</b></div>
          <div><span>Max loss</span><b>—</b></div>
        </div></div>
    </div>
    <button class="btn primary wide" id="osend" ${canTrade ? "" : "disabled"}>Review & send</button>
    <h2 class="opt-h">Chain</h2>
    <div class="table-wrap" id="chain"></div>`;

  let chain = { rows: [], expirations: [], expiration: "" };
  let spot = 0;
  let side = "buy";
  let right = "call";
  let width = 0;
  let picked = null;
  const allStrats = [...singles, ...verticals];

  function matchedStrategy() {
    if (!width) {
      if (side === "buy" && right === "call") return singles[0];
      if (side === "sell" && right === "call") return singles[1];
      if (side === "buy" && right === "put") return singles[2];
      return singles[3];
    }
    if (side === "buy" && right === "call") return verticals[0];
    if (side === "sell" && right === "call") return verticals[1];
    if (side === "buy" && right === "put") return verticals[2];
    return verticals[3];
  }

  function setBuilderOpen(open) {
    $("#builder-panel").hidden = !open;
    $("#builder-btn").setAttribute("aria-pressed", String(open));
  }

  function applyStrat(id) {
    const s = allStrats.find((x) => x.id === id);
    if (!s) return;
    side = s.side;
    right = s.right;
    width = s.width;
    $$("[data-oside]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.oside === side)));
    $$("[data-oright]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.oright === right)));
    $$("[data-owidth]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.owidth) === width)));
    fillStrikes();
    rebuildPreview();
    setBuilderOpen(false);
  }

  function nearestIndex() {
    const rows = chain.rows || [];
    if (!rows.length) return 0;
    let best = 0, dist = Infinity;
    rows.forEach((r, i) => {
      const d = Math.abs(Number(r.strike) - (spot || Number(r.strike)));
      if (d < dist) { dist = d; best = i; }
    });
    return best;
  }

  function fillStrikes() {
    const rows = chain.rows || [];
    const atm = nearestIndex();
    const keep = $("#ostrike").value;
    const selected = keep !== "" && rows[Number(keep)] ? Number(keep) : atm;
    $("#ostrike").innerHTML = rows.map((r, i) => {
      const mark = i === atm ? " · ATM" : "";
      return `<option value="${i}" ${i === selected ? "selected" : ""}>${Number(r.strike).toFixed(2)}${mark}</option>`;
    }).join("");
  }

  function farIndex() {
    const rows = chain.rows || [];
    const i = Number($("#ostrike").value || nearestIndex());
    if (!width) return -1;
    const dir = right === "call" ? 1 : -1;
    return i + dir * width;
  }

  function updateFarStrike() {
    const rows = chain.rows || [];
    const j = farIndex();
    const el = $("#ofar");
    if (!el) return;
    if (!width) {
      el.value = "Single leg";
      return;
    }
    el.value = rows[j] ? Number(rows[j].strike).toFixed(2) : "No strike that wide";
  }

  function expLabel(iso) {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00");
    if (Number.isNaN(d.getTime())) return iso;
    const days = Math.round((d - new Date(new Date().toDateString())) / 86400000);
    const when = d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    return `${when} · ${days}d`;
  }

  function legFill(leg) {
    const bid = Number(leg.bid) || 0;
    const ask = Number(leg.ask) || 0;
    if (leg.side === "buy") return ask || (bid && ask ? (bid + ask) / 2 : bid);
    return bid || (bid && ask ? (bid + ask) / 2 : ask);
  }

  function strategyRisk(legs) {
    const qty = Math.max(1, Number($("#oqty")?.value) || 1);
    if (!legs.length) return null;
    let net = 0;
    let priced = true;
    const rawLimit = ($("#olimit")?.value || "").trim();
    if (rawLimit !== "" && Number.isFinite(Number(rawLimit))) {
      net = (side === "buy" ? 1 : -1) * Math.abs(Number(rawLimit));
    } else {
      for (const l of legs) {
        const px = legFill(l);
        if (!px) priced = false;
        net += (l.side === "buy" ? 1 : -1) * px;
      }
    }
    const prem = Math.abs(net) * 100 * qty;
    const kind = net > 0.0005 ? "debit" : net < -0.0005 ? "credit" : "even";
    const s = matchedStrategy();
    const strikes = legs.map((l) => Number(l.strike)).filter(Number.isFinite);
    const widthPts = strikes.length > 1 ? Math.abs(Math.max(...strikes) - Math.min(...strikes)) : 0;
    const defined = widthPts * 100 * qty;
    let maxWin = "—";
    let maxLoss = "—";
    let note = "";
    if (s.id === "long_call") {
      maxLoss = prem;
      maxWin = "Unlimited";
    } else if (s.id === "long_put") {
      maxLoss = prem;
      maxWin = Math.max(0, Number(legs[0].strike) * 100 * qty - prem);
    } else if (s.id === "covered_call") {
      const k = Number(legs[0].strike);
      maxWin = prem + Math.max(0, k - (spot || k)) * 100 * qty;
      maxLoss = Math.max(0, (spot || 0) * 100 * qty - prem);
      note = "If you already hold 100 shares per contract at the current price.";
    } else if (s.id === "csp") {
      maxWin = prem;
      maxLoss = Math.max(0, Number(legs[0].strike) * 100 * qty - prem);
    } else if (widthPts) {
      if (kind === "debit") {
        maxLoss = prem;
        maxWin = Math.max(0, defined - prem);
      } else {
        maxWin = prem;
        maxLoss = Math.max(0, defined - prem);
      }
    }
    return { kind, prem, priced, maxWin, maxLoss, note, qty };
  }

  function riskMoney(v) {
    if (v === "Unlimited" || v === "—") return v;
    if (!Number.isFinite(Number(v))) return "—";
    return money(v);
  }

  function currentLegs() {
    const rows = chain.rows || [];
    const i = Number($("#ostrike").value || nearestIndex());
    const w = width;
    const longRow = rows[i];
    if (!longRow) return [];
    const primary = longRow[right];
    if (!primary?.symbol) return [];
    if (!w) {
      return [{ symbol: primary.symbol, side, strike: longRow.strike, right, bid: primary.bid, ask: primary.ask }];
    }
    const dir = right === "call" ? 1 : -1;
    const j = i + dir * w;
    const other = rows[j];
    if (!other?.[right]?.symbol) return [{ symbol: primary.symbol, side, strike: longRow.strike, right, bid: primary.bid, ask: primary.ask }];
    const shortSide = side === "buy" ? "sell" : "buy";
    return [
      { symbol: primary.symbol, side, strike: longRow.strike, right, bid: primary.bid, ask: primary.ask },
      { symbol: other[right].symbol, side: shortSide, strike: other.strike, right, bid: other[right].bid, ask: other[right].ask },
    ];
  }

  function rebuildPreview() {
    const s = matchedStrategy();
    $$("[data-strat]").forEach((b) => b.classList.toggle("on", b.dataset.strat === s.id));
    updateFarStrike();
    const legs = currentLegs();
    const widthLabel = width ? `${width} wide` : "single leg";
    const legsHtml = legs.length
      ? legs.map((l) => `${l.side.toUpperCase()} ${l.right} ${Number(l.strike).toFixed(2)} · ${l.symbol}`).join("<br>")
      : "Load a symbol. Alpaca Cove will build the legs from your picks.";
    const missingFar = width > 0 && legs.length < 2;
    const risk = strategyRisk(legs);
    let riskHtml = `<div class="opt-risk">
      <div><span>Debit / Credit</span><b>—</b></div>
      <div><span>Max win</span><b>—</b></div>
      <div><span>Max loss</span><b>—</b></div>
    </div>`;
    if (risk && legs.length) {
      const flow = !risk.priced ? "Quotes missing"
        : risk.kind === "debit" ? `Debit ${money(risk.prem)}`
        : risk.kind === "credit" ? `Credit ${money(risk.prem)}`
        : "Even";
      riskHtml = `<div class="opt-risk">
        <div><span>Debit / Credit</span><b class="${risk.kind === "credit" ? "up" : ""}">${flow}</b></div>
        <div><span>Max win</span><b class="up">${riskMoney(risk.maxWin)}</b></div>
        <div><span>Max loss</span><b class="down">${riskMoney(risk.maxLoss)}</b></div>
      </div>${risk.note ? `<p class="muted">${risk.note}</p>` : ""}
      <p class="muted">For ${risk.qty} contract${risk.qty === 1 ? "" : "s"}. Uses bid to sell and ask to buy. Excludes fees.</p>
      ${missingFar ? `<p class="muted">No second strike that wide. Pick a closer anchor or a smaller width.</p>` : ""}`;
    }
    $("#opreview").innerHTML = `${payoffSVG(s.id)}<b>${s.name}</b><p class="muted">${s.bias} · ${widthLabel}</p><p class="muted" id="olegs">${legsHtml}</p>${riskHtml}`;
  }

  async function load(exp) {
    const und = $("#und").value.trim().toUpperCase();
    const q = new URLSearchParams({ underlying: und });
    if (exp) q.set("expiration", exp);
    const [data, asset] = await Promise.all([
      api("/api/options/chain?" + q),
      api("/api/asset?symbol=" + encodeURIComponent(und)),
    ]);
    if (!data.ok) return toast(data.error, true);
    chain = data;
    spot = Number(asset.quote?.last || asset.quote?.ap || 0);
    $("#ounder").textContent = `${und} · ${spot ? money(spot) : "—"} · ${(data.expirations || []).length} expirations · ${(data.rows || []).length} strikes`;
    $("#olength").innerHTML = (data.expirations || []).map((e) => `<option value="${e}" ${e === data.expiration ? "selected" : ""}>${expLabel(e)}</option>`).join("");
    $("#exps").innerHTML = (data.expirations || []).map((e) => `<button class="btn" data-e="${e}" ${e === data.expiration ? 'aria-pressed="true"' : ""}>${expLabel(e)}</button>`).join("");
    $$("#exps [data-e]").forEach((b) => b.onclick = () => load(b.dataset.e));
    fillStrikes();
    rebuildPreview();
    $("#chain").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Call bid/ask</th><th>Strike</th><th>Put bid/ask</th></tr></thead><tbody>
      ${(data.rows || []).map((r) => `<tr>
        <td>${r.call ? `<button class="btn" data-occ="${r.call.symbol}" data-strike="${r.strike}" data-occ-right="call">${money(r.call.bid, 2)} / ${money(r.call.ask, 2)}</button>` : "—"}</td>
        <td>${r.strike}</td>
        <td>${r.put ? `<button class="btn" data-occ="${r.put.symbol}" data-strike="${r.strike}" data-occ-right="put">${money(r.put.bid, 2)} / ${money(r.put.ask, 2)}</button>` : "—"}</td>
      </tr>`).join("")}</tbody></table></div>`;
    $$("[data-occ]").forEach((b) => b.onclick = () => {
      picked = b.dataset.occ;
      right = b.dataset.occRight || right;
      const idx = (chain.rows || []).findIndex((r) => Number(r.strike) === Number(b.dataset.strike));
      if (idx >= 0) $("#ostrike").value = String(idx);
      $$("[data-oright]").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.oright === right)));
      rebuildPreview();
      toast("Selected " + picked);
    });
  }

  $("#builder-btn").onclick = () => setBuilderOpen($("#builder-panel").hidden);
  $$("[data-strat]").forEach((b) => b.onclick = () => applyStrat(b.dataset.strat));
  $$("[data-oside]").forEach((b) => b.onclick = () => {
    side = b.dataset.oside;
    $$("[data-oside]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    rebuildPreview();
  });
  $$("[data-oright]").forEach((b) => b.onclick = () => {
    right = b.dataset.oright;
    $$("[data-oright]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    rebuildPreview();
  });
  $$("[data-owidth]").forEach((b) => b.onclick = () => {
    width = Number(b.dataset.owidth);
    $$("[data-owidth]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    rebuildPreview();
  });
  $("#olength").onchange = () => load($("#olength").value);
  $("#ostrike").onchange = rebuildPreview;
  $("#oqty").oninput = rebuildPreview;
  $("#olimit").oninput = rebuildPreview;
  $("#oload").onclick = () => load();
  $("#osend").onclick = async () => {
    const legs = currentLegs();
    const qty = $("#oqty").value || "1";
    const limit = $("#olimit").value || null;
    if (picked && !legs.length) {
      const out = await api("/api/orders", { method: "POST", body: JSON.stringify({ symbol: picked, side, type: limit ? "limit" : "market", qty, asset_class: "option", position_intent: side === "buy" ? "buy_to_open" : "sell_to_open", limit_price: limit }) });
      return toast(out.ok ? "Option order sent" : out.error, !out.ok);
    }
    if (!legs.length) return toast("Pick a strike and load the chain first", true);
    const summary = legs.map((l) => `${l.side} ${l.right} ${l.strike}`).join(" + ");
    if (!confirm("Send " + summary + "?")) return;
    if (legs.length === 1) {
      const l = legs[0];
      const out = await api("/api/orders", { method: "POST", body: JSON.stringify({ symbol: l.symbol, side: l.side, type: limit ? "limit" : "market", qty, asset_class: "option", position_intent: l.side === "buy" ? "buy_to_open" : "sell_to_open", limit_price: limit }) });
      return toast(out.ok ? "Option order sent" : out.error, !out.ok);
    }
    const out = await api("/api/orders", {
      method: "POST",
      body: JSON.stringify({
        symbol: $("#und").value.trim(),
        side: legs[0].side,
        type: limit ? "limit" : "market",
        qty,
        asset_class: "option",
        order_class: "mleg",
        limit_price: limit,
        legs: legs.map((l) => ({
          symbol: l.symbol,
          side: l.side,
          ratio_qty: "1",
          position_intent: l.side === "buy" ? "buy_to_open" : "sell_to_open",
        })),
      }),
    });
    toast(out.ok ? "Spread sent" : out.error, !out.ok);
  };
  rebuildPreview();
  load();
}

async function calendar(me) {
  const root = $("#view");
  if (needLink(me.connection, root)) return;
  const now = new Date();
  async function show(y, m) {
    const data = await api(`/api/calendar/pnl?year=${y}&month=${m}`);
    if (!data.ok) return showAlpacaError(root, data.error);
    root.innerHTML = `
      <div class="row"><h1 class="page">${data.label}</h1>
        <div class="seg"><button class="btn" id="prev">Prev</button><button class="btn" id="next">Next</button></div></div>
      <p>Month P&L <b class="${clsPL(data.sum)}">${money(data.sum)}</b></p>
      <div class="cal">${data.weekdays.map((d) => `<div class="hd">${d}</div>`).join("")}
        ${data.weeks.flat().map((d) => d ? `<div class="day ${d.has ? clsPL(d.pl) : ""}"><div>${d.day}</div><div>${d.has ? money(d.pl) : ""}</div></div>` : `<div class="day empty"></div>`).join("")}
      </div>`;
    $("#prev").onclick = () => show(m === 1 ? y - 1 : y, m === 1 ? 12 : m - 1);
    $("#next").onclick = () => show(m === 12 ? y + 1 : y, m === 12 ? 1 : m + 1);
  }
  show(now.getFullYear(), now.getMonth() + 1);
}

async function dividends(me) {
  const root = $("#view");
  if (needLink(me.connection, root)) return;
  const now = new Date();
  async function show(y, m) {
    const data = await api(`/api/calendar/dividends?year=${y}&month=${m}`);
    if (!data.ok) return showAlpacaError(root, data.error);
    root.innerHTML = `
      <div class="row"><h1 class="page">Dividend calendar · ${data.label}</h1>
        <div class="seg"><button class="btn" id="prev">Prev</button><button class="btn" id="next">Next</button></div></div>
      <div class="cal">${data.weekdays.map((d) => `<div class="hd">${d}</div>`).join("")}
        ${data.weeks.flat().map((d) => d ? `<div class="day"><div>${d.day}</div>${(d.items||[]).map(i => `<div>${i.symbol} ${i.kind}</div>`).join("")}</div>` : `<div class="day empty"></div>`).join("")}
      </div>
      <h3>Upcoming on holdings</h3>
      <div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Ex</th><th>Payable</th><th>Est. cash</th></tr></thead>
      <tbody>${(data.upcoming||[]).map(e => `<tr><td>${e.symbol}</td><td>${e.ex_date}</td><td>${e.payable_date}</td><td>${money(e.estimate)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">No upcoming dividend announcements on current holdings.</td></tr>`}</tbody></table></div>
      <h3>Posted</h3>
      <div class="table-wrap"><table><thead><tr><th>Date</th><th>Symbol</th><th>Net</th></tr></thead>
      <tbody>${(data.posted||[]).map(e => `<tr><td>${e.date}</td><td>${e.symbol}</td><td>${money(e.net)}</td></tr>`).join("") || `<tr><td colspan="3" class="muted">No dividend activity yet. Paper accounts do not credit dividends.</td></tr>`}</tbody></table></div>`;
    $("#prev").onclick = () => show(m === 1 ? y - 1 : y, m === 1 ? 12 : m - 1);
    $("#next").onclick = () => show(m === 12 ? y + 1 : y, m === 12 ? 1 : m + 1);
  }
  show(now.getFullYear(), now.getMonth() + 1);
}

async function activity(me) {
  const root = $("#view");
  if (needLink(me.connection, root)) return;
  const [orders, acts] = await Promise.all([api("/api/orders"), api("/api/activities")]);
  if (!orders.ok) return showAlpacaError(root, orders.error);
  if (!acts.ok) return showAlpacaError(root, acts.error);
  root.innerHTML = `
    <h1 class="page">Activity</h1>
    <h3>Orders</h3>
    <div class="table-wrap"><table><thead><tr><th>When</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Status</th><th></th></tr></thead>
    <tbody>${(orders.orders||[]).map(o => `<tr>
      <td>${(o.submitted_at||"").slice(0,16)}</td><td>${o.symbol}</td><td>${o.side}</td>
      <td>${o.qty || o.notional || ""}</td><td>${o.status}</td>
      <td>${["new","accepted","partially_filled"].includes(o.status) ? `<button class="btn" data-c="${o.id}">Cancel</button>` : ""}</td>
    </tr>`).join("")}</tbody></table></div>
    <h3>Account activity</h3>
    <div class="table-wrap"><table><thead><tr><th>Type</th><th>Symbol</th><th>Net</th><th>Date</th></tr></thead>
    <tbody>${(acts.activities||[]).map(a => `<tr><td>${a.activity_type}</td><td>${a.symbol||""}</td><td>${a.net_amount||a.price||""}</td><td>${(a.date||a.transaction_time||"").toString().slice(0,10)}</td></tr>`).join("")}</tbody></table></div>`;
  $$("[data-c]").forEach((b) => b.onclick = async () => {
    const out = await api("/api/orders/" + b.dataset.c, { method: "DELETE" });
    toast(out.ok ? "Canceled" : out.error, !out.ok);
    activity(me);
  });
}

async function alerts(me) {
  const root = $("#view");
  const data = await api("/api/alerts");
  const p = data.prefs || {};
  const prefLabels = {
    fills: "Fills",
    orders: "Orders",
    dividends: "Dividends",
    dividend_upcoming: "Upcoming dividends",
    price_alerts: "Price alerts",
    options_expiry: "Option expiry",
    trial: "Trial notes",
  };
  root.innerHTML = `
    <h1 class="page">Alerts</h1>
    <p class="muted">Fills, dividends, upcoming ex-dates, option expiration, and price crosses. They land here. Turn on Email alerts below if you also want them in your inbox. Allow banners when the browser asks so you get a pop-up while the app is open.</p>
    ${(data.notifications||[]).map(n => `<div class="list-item"><div><b>${n.title}</b><div class="muted">${n.body || ""}</div></div><span class="muted">${(n.created_at || "").slice(0,16)}</span></div>`).join("") || `<p class="muted">No alerts yet. They appear after you link Alpaca and the scanner runs.</p>`}
    <button class="btn" id="read">Mark all read</button>
    <h3>Price alerts</h3>
    ${(data.price_alerts||[]).map(a => `<div class="list-item"><div>${a.symbol} ${a.op} ${a.price} ${a.active?"":"(fired)"}</div><button class="btn" data-adel="${a.id}">Remove</button></div>`).join("") || `<p class="muted">None yet. Open Trade and tap Price alert.</p>`}
    <div class="card" style="margin-top:18px">
      <h3>Email alerts</h3>
      <label class="chk"><input type="checkbox" data-pref="email_alerts" ${p.email_alerts ? "checked" : ""}> Email me when an alert is saved</label>
      <p class="muted">Goes to the Gmail on this login (${me.email || "your account"}). Open it and check Spam. The sender is onboarding@resend.dev.</p>
      <button class="btn" id="testmail" type="button">Send test email</button>
    </div>
    <h3>What to include</h3>
    ${Object.entries(prefLabels).map(([k,label]) => `<label class="chk"><input type="checkbox" data-pref="${k}" ${p[k]?"checked":""}> ${label}</label>`).join("")}`;
  $("#read").onclick = async () => { await api("/api/notifications/read-all", { method: "POST" }); alerts(me); };
  $$("[data-adel]").forEach((b) => b.onclick = async () => {
    await api("/api/alerts/" + b.dataset.adel, { method: "DELETE" });
    alerts(me);
  });
  $$("[data-pref]").forEach((box) => box.onchange = () => api("/api/prefs", { method: "POST", body: JSON.stringify({ [box.dataset.pref]: box.checked }) }));
  $("#testmail").onclick = async () => {
    const out = await api("/api/alerts/test-email", { method: "POST" });
    toast(out.ok ? `Test sent to ${out.sent_to || me.email}` : (out.error || "Email did not send."), !out.ok);
  };
}

async function account(me) {
  const root = $("#view");
  const e = me.entitlement;
  root.innerHTML = `
    <h1 class="page">Account</h1>
    <div class="metrics">
      <div class="metric"><span>Signed in</span><b>${me.email}</b></div>
      <div class="metric"><span>Access</span><b>${e.lifetime ? "Lifetime" : e.subscribed ? "Pro" : e.trial ? `Trial · ${e.trial_days_left}d left` : "Expired"}</b></div>
      <div class="metric"><span>Alpaca</span><b>${me.connection.linked ? (me.connection.paper ? "Paper" : "Live") + " · " + (me.connection.account_tail || "") : "Not linked"}</b></div>
    </div>
    <div class="card">
      <h3>Link Alpaca</h3>
      <p class="muted">Alpaca Cove is only an interface for Alpaca users. Keys stay encrypted on this server. Every trade you send is executed by Alpaca, not by us.</p>
      <p class="muted">Use <b>Paper</b> keys from app.alpaca.markets. The key ID must start with <b>PK</b>. If you see “unauthorized”, generate a new pair and paste both fields again. Live keys start with AK and only work with Paper unchecked.</p>
      ${me.oauth_configured ? `<p><a class="btn" href="/connect/alpaca?env=paper">Connect paper via OAuth</a>
        <a class="btn" href="/connect/alpaca?env=live">Connect live via OAuth</a></p>` : `<p class="muted">Add ALPACA_OAUTH_CLIENT_ID to enable one-click Connect.</p>`}
      <label>API key</label><input id="k">
      <label>Secret key</label><input id="s" type="password">
      <label><input type="checkbox" id="paper" checked style="width:auto"> Paper</label>
      <button class="btn primary" id="save">Save keys</button>
      <button class="btn" id="disc">Disconnect</button>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>Subscription</h3>
      <p class="muted">7 days free, then ${me.price_label || "$9.99"} each month or ${me.lifetime_label || "$199"} once. Open <a href="/upgrade">Upgrade</a> to pick a plan.</p>
    </div>
    <div class="card" style="margin-top:16px">
      <h3>Delete account</h3>
      <p class="muted">Removes your Cove login, stored Alpaca keys, watchlist, alerts, and feedback. Does not close Alpaca. Cancel Google Play or App Store billing separately if you pay.</p>
      <p class="muted">Web path (no app needed): <a href="/delete-account">Delete account page</a>.</p>
      <label>Type your Cove password</label>
      <input id="del-pass" type="password" autocomplete="current-password">
      <button class="btn danger" id="del-acc" type="button">Delete my Cove account</button>
    </div>
    <p class="muted"><a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></p>
    <form method="post" action="/logout" style="margin-top:18px"><button class="btn">Sign out</button></form>`;
  $("#save").onclick = async () => {
    const out = await api("/api/connect/keys", { method: "POST", body: JSON.stringify({ api_key: $("#k").value, secret_key: $("#s").value, paper: $("#paper").checked }) });
    toast(out.ok ? "Alpaca linked" : out.error, !out.ok);
    if (out.ok) location.href = "/home";
  };
  $("#disc").onclick = async () => { await api("/api/connect/disconnect", { method: "POST" }); location.reload(); };
  let armed = false;
  $("#del-acc").onclick = async () => {
    const password = $("#del-pass").value;
    if (!password) return toast("Type your password first.", true);
    if (!armed) {
      armed = true;
      $("#del-acc").textContent = "Tap again to delete forever";
      return;
    }
    const out = await api("/api/account/delete", { method: "POST", body: JSON.stringify({ password }) });
    if (!out.ok) {
      armed = false;
      $("#del-acc").textContent = "Delete my Cove account";
      return toast(out.error || "Could not delete", true);
    }
    location.href = "/delete-account?done=1";
  };
}

function accessBadge(e) {
  if (e.lifetime) return "Lifetime";
  if (e.subscribed) return "Pro";
  if (e.trial) return "Trial";
  return "Free";
}

async function payPlan(plan) {
  const out = await api("/api/billing/checkout", { method: "POST", body: JSON.stringify({ plan }) });
  if (out.ok && out.url) {
    location.href = out.url;
    return;
  }
  toast(out.error || "Pay in the App Store or Google Play when those products are live.", true);
}

async function restorePurchases() {
  const out = await api("/api/billing/portal", { method: "POST" });
  if (out.ok && out.url) {
    location.href = out.url;
    return;
  }
  toast(out.error || "On a phone, restore from your Apple or Google account when the store products are live.", true);
}

function upgrade(me) {
  const e = me.entitlement || {};
  const billed = new URLSearchParams(location.search).get("billing");
  const paid = e.lifetime || e.subscribed;
  $("#view").innerHTML = `
    <div class="row">
      <h1 class="page">Upgrade</h1>
      <span class="pill">${accessBadge(e)}</span>
    </div>
    ${billed === "success" ? `<p class="flash" style="margin-bottom:16px">Payment received. Thank you.</p>` : ""}
    ${billed === "cancel" ? `<p class="muted">Checkout was cancelled. You can try again any time.</p>` : ""}
    <p class="lede-inline">7 days free. Then ${me.price_label || "$9.99"} each month, or ${me.lifetime_label || "$199"} once. You keep using the Alpaca account you already have.</p>
    ${paid ? `<div class="card"><h3>You're on ${e.lifetime ? "Lifetime" : "Pro"}</h3><p class="muted">Manage or cancel in the App Store, Google Play, or tap Restore purchases if a payment did not show up.</p></div>` : `
    <button class="btn primary wide cta-arrow" id="pay-month" type="button">
      <span class="cta-star">★</span>
      ${me.price_label || "$9.99"} / month
      <span>→</span>
    </button>
    <button class="btn primary wide cta-arrow" id="pay-life" type="button">
      <span class="cta-star">★</span>
      ${me.lifetime_label || "$199"} lifetime
      <span>→</span>
    </button>`}
    <button class="restore-row" id="restore" type="button">
      <span class="restore-ico">↺</span>
      <span><b>Restore purchases</b><span class="muted">Bring back a plan you already paid for</span></span>
      <span class="muted">›</span>
    </button>
    <p class="muted" style="margin-top:16px">Apple and Google take their store fee. Evolution Freedom LTD never holds your trading money.</p>`;
  $("#pay-month") && ($("#pay-month").onclick = () => payPlan("monthly"));
  $("#pay-life") && ($("#pay-life").onclick = () => payPlan("lifetime"));
  $("#restore").onclick = restorePurchases;
}

function share(me) {
  const company = me.company || "Evolution Freedom LTD";
  const site = (me.public_site_url || me.share_url || "https://www.evolutionfreedomltd.co.uk").replace(/\/$/, "");
  const terms = me.site_readme_url || `${site}/terms-and-conditions/`;
  $("#view").innerHTML = `
    <h1 class="page">Share</h1>
    <div class="card share-hero">
      <img class="app-logo" src="/static/img/alpaca-cove-icon.png" alt="Alpaca Cove">
      <h3>Refer a friend</h3>
      <p class="muted">Opens the Evolution Freedom website so a friend can see Alpaca Cove.</p>
      <button class="btn primary wide cta-arrow" id="sharebtn" type="button">
        <span class="cta-star">↗</span>
        Share invite
        <span>→</span>
      </button>
    </div>
    <div class="card about-card">
      <h3>About</h3>
      <p class="muted">Version ${me.version || "1.0.0"}</p>
      <p class="disclaimer-copy">This app is not affiliated with, endorsed by, or sponsored by Alpaca Markets. Alpaca is a registered trademark of AlpacaDB, Inc.</p>
      <p class="disclaimer-copy"><b>${company}</b> provides software only and is not a broker-dealer, investment adviser, exchange, custodian, or wallet provider. Nothing in the app is investment, legal, or tax advice.</p>
      <p><a class="link-blue" href="${terms}" target="_blank" rel="noopener">Terms of Service</a> · <a class="link-blue" href="${site}/privacy-page/" target="_blank" rel="noopener">Privacy</a></p>
    </div>`;
  $("#sharebtn").onclick = () => {
    window.open(site, "_blank", "noopener");
  };
}

function feedback() {
  $("#view").innerHTML = `
    <h1 class="page">Feedback</h1>
    <p class="muted">Ideas and problems. Write a note and tap Send.</p>
    <div class="card">
      <label>What is this?</label>
      <div class="seg">
        <button class="btn" data-fk="idea" aria-pressed="true">Idea</button>
        <button class="btn" data-fk="problem">Problem</button>
        <button class="btn" data-fk="other">Other</button>
      </div>
      <label>Your note</label>
      <textarea id="fmsg" rows="8" placeholder="What should we add or fix?"></textarea>
      <button class="btn primary wide" id="fsend">Send</button>
    </div>`;
  let kind = "idea";
  $$("[data-fk]").forEach((b) => b.onclick = () => {
    kind = b.dataset.fk;
    $$("[data-fk]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  });
  $("#fsend").onclick = async () => {
    const message = $("#fmsg").value.trim();
    if (message.length < 8) return toast("Write a little more so it is useful.", true);
    const out = await api("/api/feedback", { method: "POST", body: JSON.stringify({ kind, message }) });
    if (!out.ok) return toast(out.error || "Could not send", true);
    $("#fmsg").value = "";
    if (out.emailed === false) return toast(out.error || "Saved in the app, but the email did not send.", true);
    if (out.notice) return toast(out.notice, true);
    toast(`Sent to ${out.sent_to || "your inbox"}. Check Spam. Sender: onboarding@resend.dev`);
  };
}

function more(me) {
  const site = (me.public_site_url || "https://www.evolutionfreedomltd.co.uk").replace(/\/$/, "");
  const help = me.site_readme_url || `${site}/terms-and-conditions/`;
  $("#view").innerHTML = `
    <h1 class="page">More</h1>
    <p class="muted">Account, Upgrade, Share, and Feedback stay in the app. Read me opens the terms on the website.</p>
    <a class="more-link" href="/account">
      <b>Account</b>
      <span>Your Cove login, Alpaca keys, and sign out.</span>
    </a>
    <a class="more-link" href="/upgrade">
      <b>Upgrade</b>
      <span>Trial, monthly, and lifetime — pay in the app store when live.</span>
    </a>
    <a class="more-link" href="/share">
      <b>Share</b>
      <span>One button opens the Evolution Freedom website.</span>
    </a>
    <a class="more-link" href="/feedback">
      <b>Feedback</b>
      <span>Send an idea or a problem from the app.</span>
    </a>
    <a class="more-link" href="${help}" target="_blank" rel="noopener">
      <b>Read me</b>
      <span>Opens the terms page on the website.</span>
    </a>
    <p class="muted">Privacy is on the same site: <a class="link-blue" href="${site}/privacy-page/" target="_blank" rel="noopener">Privacy page</a>.</p>`;
}

function readme() {
  $("#view").innerHTML = `
    <h1 class="page">Read me</h1>
    <div class="disclaimer">
      <b>Alpaca Cove is an interface, not a broker.</b>
      This app is a desk for people who already have Alpaca. Every order you confirm is sent to Alpaca and filled there.
      We never hold your cash or shares. Evolution Freedom LTD provides software only. Not investment advice. Options can expire worthless.
    </div>
    <div class="card help-sec">
      <h2>How the app works</h2>
      <p>Alpaca Cove is an iPhone and Android app. The tabs along the bottom are the trading desk. On a phone, Account, Upgrade, Share, and Feedback sit under More. Read me opens the terms on the website. If a screen looks stuck, leave the tab and open it again, or close the app fully and come back.</p>
    </div>
    <div class="card help-sec">
      <h2>First time</h2>
      <ol>
        <li>Create your Alpaca Cove login (email and password). That is only for this app.</li>
        <li>Open <a href="/account">Account</a> and link the Alpaca account you already have.</li>
        <li>Start with <b>Paper</b> if you want practice money. <b>Live</b> is real money at Alpaca.</li>
        <li>When the link works, Home, Trade, and Options will fill in.</li>
      </ol>
    </div>
    <div class="card help-sec">
      <h2>Home</h2>
      <p>Your Alpaca balances and a chart of account value. Tap 1D, 1W, 1M and the other periods to change how far back the chart looks. Pinch or drag the chart to move around. Home does not place a trade.</p>
    </div>
    <div class="card help-sec">
      <h2>Trade</h2>
      <ol>
        <li>Type a symbol (for example AAPL) and wait for the price to appear.</li>
        <li>Pick buy or sell, how many shares, and the order type (market, limit, and so on).</li>
        <li>For pre-market (4:00 am–9:30 am ET) or after hours (4:00 pm–8:00 pm ET), tick <b>Pre-market / after-hours</b>. Cove switches to a limit order. Alpaca will not fill a market order in those sessions.</li>
        <li>Read it back, then send. The order goes to Alpaca, not to us.</li>
      </ol>
      <p>On the same screen you can add the symbol to Watchlist or set a price alert.</p>
    </div>
    <div class="card help-sec">
      <h2>Watchlist</h2>
      <p>Symbols you want to glance at. Type a ticker, tap Add. Tap a row to open Trade. Remove only takes it off this list — it does not sell anything.</p>
    </div>
    <div class="card help-sec">
      <h2>Options</h2>
      <ol>
        <li>Type a stock and tap Load so dates and strikes appear.</li>
        <li>Set Buy/Sell, Call/Put, expiration, and strike width. The card on the right (or below, on a phone) names the strategy and shows debit or credit, max win, and max loss.</li>
        <li>Or tap <b>Builder</b> and pick a card (Long Call, a vertical spread, and so on). That fills the same controls for you.</li>
        <li>Read the legs, then Review &amp; send. Alpaca handles the fill.</li>
      </ol>
    </div>
    <div class="card help-sec">
      <h2>P&amp;L calendar</h2>
      <p>A month of daily profit and loss from Alpaca. Green days are up, red days are down. Prev and Next move the month. This is a report. It does not trade.</p>
    </div>
    <div class="card help-sec">
      <h2>Dividends</h2>
      <p>Ex-dates and pay dates for stocks you hold. Paper accounts do not get real dividend cash. Upcoming dates can also show under Alerts.</p>
    </div>
    <div class="card help-sec">
      <h2>Activity</h2>
      <p>Orders and account events from Alpaca — fills, cancels, dividends posted. You can cancel an open order here. The same records live in your Alpaca app or website.</p>
    </div>
    <div class="card help-sec">
      <h2>Alerts</h2>
      <p>Notes this app writes when it checks your Alpaca account (every few minutes): fills, dividends, option expiry, and price levels you set. They land in Alerts and email you if Email alerts is on. Use the ticks to turn kinds on or off.</p>
    </div>
    <div class="card help-sec">
      <h2>Account</h2>
      <ol>
        <li>This is your app login, plus the Alpaca link.</li>
        <li>Paste your Alpaca key and secret (paper or live) and tap Save keys. Or use Connect when that button is shown.</li>
        <li>Disconnect only removes the keys from this app. Your Alpaca account stays open.</li>
      </ol>
    </div>
    <div class="card help-sec">
      <h2>Upgrade</h2>
      <p>After the free week, tap monthly or lifetime on the Upgrade tab. Pay in the App Store or Google Play when those products are live. Restore purchases is on the same screen.</p>
    </div>
    <div class="card help-sec">
      <h2>Share</h2>
      <p>Tap Share invite. That opens the Evolution Freedom website so a friend can read about Alpaca Cove.</p>
    </div>
    <div class="card help-sec">
      <h2>Feedback</h2>
      <p>Open the Feedback tab, write a note, and tap Send.</p>
    </div>
    <div class="card help-sec">
      <h2>If something looks empty</h2>
      <p>Most tabs need Alpaca linked first. Open Account, save keys, then open the tab again. If a chart or chain is still blank, close the app fully and open it. You do not need a keyboard, and there is no refresh shortcut.</p>
    </div>`;
}

document.addEventListener("DOMContentLoaded", boot);
