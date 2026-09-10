from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)

APP_NAME = os.getenv("APP_NAME", "Alpaca Cove")
COMPANY_NAME = os.getenv("COMPANY_NAME", "Evolution Freedom LTD")
APP_VERSION = os.getenv("APP_VERSION", "1.0.5")
APP_SECRET = os.getenv("APP_SECRET", "dev-only-change-me")
APP_URL = os.getenv("APP_URL", "http://127.0.0.1:8787").rstrip("/")
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "https://www.evolutionfreedomltd.co.uk").rstrip("/")
SHARE_URL = os.getenv("SHARE_URL", PUBLIC_SITE_URL).rstrip("/")
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "7"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'cove.db').as_posix()}")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "").strip()
STRIPE_PRICE_LIFETIME_ID = os.getenv("STRIPE_PRICE_LIFETIME_ID", "").strip()
STRIPE_PRICE_MONTHLY_CENTS = int(os.getenv("STRIPE_PRICE_MONTHLY_CENTS", "999"))
STRIPE_PRICE_AMOUNT = int(os.getenv("STRIPE_PRICE_AMOUNT", str(STRIPE_PRICE_MONTHLY_CENTS)))
STRIPE_PRICE_LIFETIME_CENTS = int(os.getenv("STRIPE_PRICE_LIFETIME_CENTS", "19900"))

ALPACA_OAUTH_CLIENT_ID = os.getenv("ALPACA_OAUTH_CLIENT_ID", "").strip()
ALPACA_OAUTH_CLIENT_SECRET = os.getenv("ALPACA_OAUTH_CLIENT_SECRET", "").strip()
ALPACA_OAUTH_REDIRECT_URI = os.getenv(
    "ALPACA_OAUTH_REDIRECT_URI", f"{APP_URL}/connect/oauth/callback"
).strip()

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
NOTIFY_FROM = os.getenv("NOTIFY_FROM", "Alpaca Cove <onboarding@resend.dev>")
FEEDBACK_TO = os.getenv("FEEDBACK_TO", "evolutioninvestments79@gmail.com").strip()
