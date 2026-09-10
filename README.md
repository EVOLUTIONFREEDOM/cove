# Cove

Interface for an existing [Alpaca](https://alpaca.markets) brokerage account. Cove does not custody funds. Alpaca remains the broker.

## What it does

- **iPhone and Android app** (not a website product). 7-day free trial, then $9.99/month or $199 lifetime through the stores
- Link Alpaca with **API keys** (works today) or **OAuth Connect** (after you register an app)
- Trade **stocks, crypto, and options**
- **P&L calendar** from portfolio history
- **Dividend calendar** on holdings, plus fill / dividend / expiry / price alerts

## Run locally

```powershell
cd $HOME\Desktop\cove
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe run.py
```

Open http://127.0.0.1:8787

Create an account, open **Account**, paste **paper** API keys from the Alpaca dashboard (`PK…` / secret). Then use Home, Trade, Options, calendars, and Alerts.

## Subscriptions

Alpaca Cove is an **iPhone and Android app**, not a website product. Charge through App Store and Google Play: $9.99/month or $199 lifetime after a 7-day trial. Feedback is saved in the app database — it is not emailed.

## Alpaca Connect (OAuth)

Register an app under Alpaca Connect. Put `ALPACA_OAUTH_CLIENT_ID` and `ALPACA_OAUTH_CLIENT_SECRET` in `.env`. Redirect URI must match `ALPACA_OAUTH_REDIRECT_URI`. Commercial / subscription apps need Alpaca’s written approval before other people trade live through your client.

## Notifications

A scanner runs every 3 minutes (and at `POST /api/cron/tick`):

- Order fills
- Posted dividends
- Upcoming ex-dividend dates on holdings
- Option expiration 7d / 1d / today
- Price alerts you set from a symbol
- Trial ending

Add `RESEND_API_KEY` to also email those events.

Paper trading does **not** credit dividends. Upcoming announcements still show on the dividend calendar.

## iPhone and Android

Native shells are in `mobile/` (Capacitor). See **[STORE.md](STORE.md)** for App Store and Google Play steps.

```powershell
$env:PATH = "$PWD\tools\node-v22.19.0-win-x64;$env:PATH"
cd mobile
npx cap sync
npx cap open android
```

iOS is built in the cloud: push the repo, then start **Cove iPhone (TestFlight)** on [Codemagic](https://codemagic.io). Install the result with TestFlight on your iPhone. See **[STORE.md](STORE.md)**.

## Legal

Not a broker-dealer. Not investment advice. Options involve substantial risk of loss.
