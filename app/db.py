from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL, ROOT


class Base(DeclarativeBase):
    pass


def _engine():
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    return create_engine(DATABASE_URL, future=True, connect_args=connect_args)


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def migrate_sqlite() -> None:
    """Relax old NOT NULL billing columns so signup works without Stripe."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        if "notifications" in tables:
            ncols = {row[1] for row in conn.execute(text("PRAGMA table_info(notifications)"))}
            if "read" not in ncols:
                conn.execute(text("ALTER TABLE notifications ADD COLUMN read BOOLEAN DEFAULT 0"))
            if "href" not in ncols:
                conn.execute(text("ALTER TABLE notifications ADD COLUMN href VARCHAR(200) DEFAULT ''"))
            if "read_at" not in ncols:
                conn.execute(text("ALTER TABLE notifications ADD COLUMN read_at DATETIME"))
        if "users" not in tables:
            return
        info = list(conn.execute(text("PRAGMA table_info(users)")))
        names = {row[1] for row in info}
        notnull = {row[1] for row in info if row[3]}
        if "notify_prefs" not in names:
            conn.execute(text("ALTER TABLE users ADD COLUMN notify_prefs TEXT DEFAULT '{}'"))
            names.add("notify_prefs")
        if not ({"stripe_customer_id", "stripe_subscription_id"} & notnull):
            return
        conn.execute(text("DROP TABLE IF EXISTS users_new"))
        conn.execute(
            text(
                """
                CREATE TABLE users_new (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR(255) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    created_at DATETIME,
                    trial_ends_at DATETIME,
                    stripe_customer_id VARCHAR(64),
                    stripe_subscription_id VARCHAR(64),
                    stripe_status VARCHAR(32) DEFAULT 'trialing',
                    notify_prefs TEXT DEFAULT '{}'
                )
                """
            )
        )
        copy = [col for col in (
            "id",
            "email",
            "password_hash",
            "created_at",
            "trial_ends_at",
            "stripe_customer_id",
            "stripe_subscription_id",
            "stripe_status",
            "notify_prefs",
        ) if col in names or col == "notify_prefs"]
        cols = ", ".join(copy)
        conn.execute(text(f"INSERT INTO users_new ({cols}) SELECT {cols} FROM users"))
        conn.execute(text("DROP TABLE users"))
        conn.execute(text("ALTER TABLE users_new RENAME TO users"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"))


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
