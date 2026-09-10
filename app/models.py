from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime | None) -> datetime:
    if value is None:
        return utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    trial_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stripe_status: Mapped[str] = mapped_column(String(32), default="trialing")
    notify_prefs: Mapped[str] = mapped_column(Text, default="{}")
    connection: Mapped["Connection | None"] = relationship(back_populates="user", uselist=False)
    notifications: Mapped[list["Notification"]] = relationship(back_populates="user")
    alerts: Mapped[list["PriceAlert"]] = relationship(back_populates="user")
    watchlist: Mapped[list["WatchItem"]] = relationship(back_populates="user")
    prefs: Mapped["NotifyPrefs | None"] = relationship(back_populates="user", uselist=False)
    feedback: Mapped[list["Feedback"]] = relationship(back_populates="user")
    password_resets: Mapped[list["PasswordReset"]] = relationship(back_populates="user")


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship(back_populates="password_resets")


class Connection(Base):
    __tablename__ = "alpaca_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    paper: Mapped[bool] = mapped_column(Boolean, default=True)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_tail: Mapped[str] = mapped_column(String(8), default="")
    account_status: Mapped[str] = mapped_column(String(32), default="")
    last_activity_id: Mapped[str] = mapped_column(String(128), default="")
    user: Mapped[User] = relationship(back_populates="connection")


AlpacaLink = Connection


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="idea")
    message: Mapped[str] = mapped_column(Text)
    emailed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="feedback")


class WatchItem(Base):
    __tablename__ = "watch_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="watchlist")


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    op: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="alerts")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    symbol: Mapped[str] = mapped_column(String(32), default="")
    href: Mapped[str] = mapped_column(String(200), default="")
    dedupe_key: Mapped[str] = mapped_column(String(160), default="", index=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="notifications")


class NotifyPrefs(Base):
    __tablename__ = "notify_prefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    fills: Mapped[bool] = mapped_column(Boolean, default=True)
    dividends: Mapped[bool] = mapped_column(Boolean, default=True)
    orders: Mapped[bool] = mapped_column(Boolean, default=True)
    price_moves: Mapped[bool] = mapped_column(Boolean, default=True)
    option_expiry: Mapped[bool] = mapped_column(Boolean, default=True)
    trial: Mapped[bool] = mapped_column(Boolean, default=True)
    user: Mapped[User] = relationship(back_populates="prefs")


class WorkerCursor(Base):
    __tablename__ = "worker_cursors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    last_activity_id: Mapped[str] = mapped_column(String(128), default="")
    last_order_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_div_scan: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def prefs_dict(user: User) -> dict:
    raw = (user.notify_prefs or "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k): bool(v) for k, v in data.items()}
        except json.JSONDecodeError:
            pass
    prefs = user.prefs
    if not prefs:
        return {}
    return {
        "fills": prefs.fills,
        "orders": prefs.orders,
        "dividends": prefs.dividends,
        "dividend_upcoming": True,
        "price_alerts": prefs.price_moves,
        "options_expiry": prefs.option_expiry,
        "trial": prefs.trial,
    }
