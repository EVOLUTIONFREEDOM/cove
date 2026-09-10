from __future__ import annotations

from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import APP_NAME, APP_SECRET, APP_URL, ROOT
from app.db import Base, engine, migrate_sqlite
from app import models  # noqa: F401 — register tables on Base.metadata
from app.routers import api, pages
from app.worker import run_once


scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_sqlite()
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    scheduler.add_job(run_once, "interval", minutes=3, id="cove-scan", replace_existing=True)
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SECRET,
    same_site="lax",
    https_only=APP_URL.startswith("https"),
)
app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")
app.include_router(pages.router)
app.include_router(api.router)


@app.get("/health")
def health():
    return {"ok": True}


@app.middleware("http")
async def cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif not path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response
