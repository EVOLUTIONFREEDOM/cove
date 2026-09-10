from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import APP_SECRET, TRIAL_DAYS
from app.models import PasswordReset, User, aware, utcnow


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_user(db: Session, email: str, password: str) -> User:
    user = User(
        email=email.lower().strip(),
        password_hash=hash_password(password),
        trial_ends_at=utcnow() + timedelta(days=TRIAL_DAYS),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def current_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.get(User, int(uid))


def require_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def set_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_reset_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    row = PasswordReset(
        user_id=user.id,
        token_hash=_token_hash(token),
        expires_at=utcnow() + timedelta(hours=1),
    )
    db.add(row)
    db.commit()
    return token


def user_for_reset_token(db: Session, token: str) -> User | None:
    if not token:
        return None
    row = db.query(PasswordReset).filter(PasswordReset.token_hash == _token_hash(token)).first()
    if not row or row.used_at is not None:
        return None
    if aware(row.expires_at) < utcnow():
        return None
    return db.get(User, row.user_id)


def consume_reset_token(db: Session, token: str) -> User | None:
    user = user_for_reset_token(db, token)
    if not user:
        return None
    row = db.query(PasswordReset).filter(PasswordReset.token_hash == _token_hash(token)).first()
    if row:
        row.used_at = utcnow()
        db.commit()
    return user


def login_user(request: Request, user: User) -> None:
    request.session["user_id"] = user.id
    request.session["v"] = APP_SECRET[:8]


def logout_user(request: Request) -> None:
    request.session.clear()
