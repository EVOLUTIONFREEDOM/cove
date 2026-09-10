from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import (
    Connection,
    Feedback,
    Notification,
    NotifyPrefs,
    PasswordReset,
    PriceAlert,
    User,
    WatchItem,
    WorkerCursor,
)


def wipe_user(db: Session, user: User) -> None:
    uid = user.id
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == uid))
    db.execute(delete(Feedback).where(Feedback.user_id == uid))
    db.execute(delete(WatchItem).where(WatchItem.user_id == uid))
    db.execute(delete(PriceAlert).where(PriceAlert.user_id == uid))
    db.execute(delete(Notification).where(Notification.user_id == uid))
    db.execute(delete(NotifyPrefs).where(NotifyPrefs.user_id == uid))
    db.execute(delete(WorkerCursor).where(WorkerCursor.user_id == uid))
    db.execute(delete(Connection).where(Connection.user_id == uid))
    db.delete(user)
    db.commit()
