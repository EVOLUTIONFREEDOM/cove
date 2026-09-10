from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import wipe_user
from app.auth import (
    consume_reset_token,
    create_reset_token,
    create_user,
    current_user,
    login_user,
    logout_user,
    set_password,
    user_for_reset_token,
    verify_password,
)
from app.config import APP_NAME, APP_URL, APP_VERSION, COMPANY_NAME, FEEDBACK_TO, PUBLIC_SITE_URL, ROOT, STRIPE_PRICE_AMOUNT, STRIPE_PRICE_LIFETIME_CENTS, TRIAL_DAYS
from app.db import get_db
from app.entitlements import connection_payload, entitlement_state
from app.models import User
from app.notifications import send_mail, unread_count
from app.billing import stripe_ready

templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
router = APIRouter()


def ctx(request: Request, db: Session, **extra):
    user = current_user(request, db)
    payload = {
        "request": request,
        "app_name": APP_NAME,
        "company_name": COMPANY_NAME,
        "app_version": APP_VERSION,
        "user": user,
        "entitlement": entitlement_state(user) if user else None,
        "connection": connection_payload(user.connection) if user else {"linked": False},
        "unread": unread_count(db, user) if user else 0,
        "trial_days": TRIAL_DAYS,
        "public_site_url": PUBLIC_SITE_URL,
        "price_label": f"${STRIPE_PRICE_AMOUNT / 100:.2f}/mo",
        "lifetime_label": f"${STRIPE_PRICE_LIFETIME_CENTS / 100:.0f}",
        "stripe_ready": stripe_ready(),
        "flash": request.session.pop("flash", None),
        "reset_link": extra.get("reset_link") or request.session.pop("reset_link", None),
        "page": extra.get("page", ""),
    }
    payload.update(extra)
    return payload


def signed_in(request: Request, db: Session) -> User | RedirectResponse:
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return user


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "privacy.html", ctx(request, db, page="privacy"))


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "terms.html", ctx(request, db, page="terms"))


@router.get("/", response_class=HTMLResponse)
def landing(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/home", status_code=302)
    return templates.TemplateResponse(request, "landing.html", ctx(request, db, page="landing"))


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/home", status_code=302)
    return templates.TemplateResponse(request, "auth.html", ctx(request, db, mode="login", page="login"))


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/home", status_code=302)
    return templates.TemplateResponse(request, "auth.html", ctx(request, db, mode="signup", page="signup"))


@router.post("/login")
def login_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
):
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if not user or not verify_password(password, user.password_hash):
        request.session["flash"] = "Email or password is wrong."
        return RedirectResponse("/login", status_code=303)
    login_user(request, user)
    return RedirectResponse("/home", status_code=303)


@router.post("/signup")
def signup_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
):
    email_n = email.lower().strip()
    if len(password) < 8:
        request.session["flash"] = "Use at least 8 characters."
        return RedirectResponse("/signup", status_code=303)
    if db.scalar(select(User).where(User.email == email_n)):
        request.session["flash"] = "That email already has an account."
        return RedirectResponse("/signup", status_code=303)
    user = create_user(db, email_n, password)
    login_user(request, user)
    return RedirectResponse("/home", status_code=303)


@router.get("/forgot", response_class=HTMLResponse)
def forgot_form(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/home", status_code=302)
    return templates.TemplateResponse(request, "auth.html", ctx(request, db, mode="forgot", page="forgot"))


@router.post("/forgot")
def forgot_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
):
    email_n = email.lower().strip()
    user = db.scalar(select(User).where(User.email == email_n))
    host = (request.url.hostname or "").lower()
    local = host in {"127.0.0.1", "localhost"}
    if user:
        token = create_reset_token(db, user)
        reset_url = f"{APP_URL}/reset?token={token}"
        body = (
            "You asked to reset your Alpaca Cove password.\n\n"
            "Open this link. It works for one hour:\n"
            f"{reset_url}\n\n"
            "If you did not ask for this, ignore the email.\n"
        )
        ok, _err = send_mail(user.email, "Reset your Alpaca Cove password", body)
        backup = (FEEDBACK_TO or "").strip()
        if not ok and backup and backup.lower() != email_n:
            ok, _err = send_mail(
                backup,
                "Reset your Alpaca Cove password",
                f"This reset is for the Cove login {email_n}.\n\n{body}",
            )
        if ok:
            request.session["flash"] = "Check your email for a reset link. Look in junk if you do not see it."
        elif local:
            request.session["flash"] = "The reset email did not send. Use the link below on this computer. It lasts one hour."
            request.session["reset_link"] = reset_url
        else:
            request.session["flash"] = "If that email is on an account, we sent a reset link. Check inbox and junk."
    else:
        request.session["flash"] = "If that email is on an account, we sent a reset link. Check inbox and junk."
    return RedirectResponse("/forgot", status_code=303)


@router.get("/reset", response_class=HTMLResponse)
def reset_form(request: Request, db: Session = Depends(get_db), token: str = ""):
    if current_user(request, db):
        return RedirectResponse("/home", status_code=302)
    if not user_for_reset_token(db, token):
        request.session["flash"] = "That reset link is old or already used. Ask for a new one."
        return RedirectResponse("/forgot", status_code=303)
    return templates.TemplateResponse(
        request, "auth.html", ctx(request, db, mode="reset", page="reset", token=token)
    )


@router.post("/reset")
def reset_post(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Form(""),
    password: str = Form(...),
    password2: str = Form(""),
):
    if len(password) < 8:
        request.session["flash"] = "Use at least 8 characters."
        return RedirectResponse(f"/reset?token={token}", status_code=303)
    if password != password2:
        request.session["flash"] = "The two passwords do not match."
        return RedirectResponse(f"/reset?token={token}", status_code=303)
    user = consume_reset_token(db, token)
    if not user:
        request.session["flash"] = "That reset link is old or already used. Ask for a new one."
        return RedirectResponse("/forgot", status_code=303)
    set_password(user, password)
    db.commit()
    login_user(request, user)
    request.session["flash"] = "Password updated. You are signed in."
    return RedirectResponse("/home", status_code=303)


@router.post("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/", status_code=303)


@router.get("/delete-account", response_class=HTMLResponse)
def delete_account_form(request: Request, db: Session = Depends(get_db), done: str = ""):
    return templates.TemplateResponse(
        request,
        "delete_account.html",
        ctx(request, db, page="delete-account", deleted=done == "1"),
    )


@router.post("/delete-account")
def delete_account_post(
    request: Request,
    db: Session = Depends(get_db),
    email: str = Form(...),
    password: str = Form(...),
    confirm: str = Form(""),
):
    email_n = email.lower().strip()
    if confirm.strip().upper() != "DELETE":
        request.session["flash"] = "Type DELETE in the confirm box to go ahead."
        return RedirectResponse("/delete-account", status_code=303)
    user = db.scalar(select(User).where(User.email == email_n))
    if not user or not verify_password(password, user.password_hash):
        request.session["flash"] = "Email or password is wrong."
        return RedirectResponse("/delete-account", status_code=303)
    wipe_user(db, user)
    logout_user(request)
    return RedirectResponse("/delete-account?done=1", status_code=303)


def _app_page(name: str):
    def view(request: Request, db: Session = Depends(get_db)):
        user = current_user(request, db)
        if not user:
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(request, "app.html", ctx(request, db, page=name))

    view.__name__ = f"page_{name}"
    return view


for path, name in [
    ("/home", "home"),
    ("/trade", "trade"),
    ("/watchlist", "watchlist"),
    ("/options", "options"),
    ("/calendar", "calendar"),
    ("/dividends", "dividends"),
    ("/activity", "activity"),
    ("/alerts", "alerts"),
    ("/account", "account"),
    ("/upgrade", "upgrade"),
    ("/share", "share"),
    ("/feedback", "feedback"),
    ("/readme", "readme"),
    ("/more", "more"),
]:
    router.add_api_route(path, _app_page(name), methods=["GET"], response_class=HTMLResponse)
