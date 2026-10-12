"""
Database setup.

Defaults to SQLite for a zero-config local-first start. To move to
PostgreSQL later, set DATABASE_URL, e.g.:

    DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/studyhub

No other code needs to change — SQLAlchemy abstracts the rest.
"""

"""
Database setup.

Defaults to SQLite for a zero-config local-first start. To move to
PostgreSQL later, set DATABASE_URL, e.g.:

    DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/studyhub

No other code needs to change — SQLAlchemy abstracts the rest. (On
Postgres, use a real migration tool such as Alembic instead of the
lightweight SQLite auto-migration below.)
"""

import os
import logging
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger("database")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SQLITE_PATH = os.path.join(BASE_DIR, "data", "studyhub.db")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _run_sqlite_auto_migration():
    """`create_all()` only creates tables that don't exist yet — it never
    adds a column to a table that's already there. Since this project has
    added columns to `users` and other tables across iterations (auth,
    multi-provider AI settings, confidence-scored deadlines, ...), an
    existing studyhub.db from before those changes is missing them, which
    surfaces as `OperationalError: no such column: ...` the first time
    that column is queried.

    This adds any missing column, non-destructively, by diffing each
    model's columns against what's actually in the SQLite file. Existing
    rows get NULL (or the type's zero value) in the new column, which is
    fine here since every added column so far is optional/has an
    application-level default.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return  # Use a real migration tool (Alembic) for Postgres.

    inspector = sa.inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # brand-new table — create_all() already handled it
            existing_cols = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                col_type = column.type.compile(engine.dialect)
                logger.warning("Migrating database: adding %s.%s (%s)", table.name, column.name, col_type)
                conn.execute(sa.text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


def init_db():
    os.makedirs(os.path.dirname(DEFAULT_SQLITE_PATH), exist_ok=True)
    import backend.models  # noqa: F401 register models on Base before create_all
    Base.metadata.create_all(bind=engine)
    _run_sqlite_auto_migration()
    # Backfill username for accounts created before username support.
    if DATABASE_URL.startswith("sqlite"):
        with engine.begin() as conn:
            cols = {c["name"] for c in sa.inspect(engine).get_columns("users")}
            if "username" in cols:
                rows = conn.execute(sa.text("SELECT id, email, username FROM users")).fetchall()
                used = {r[2] for r in rows if r[2]}
                for user_id, email, username in rows:
                    if username:
                        continue
                    base = (email.split("@")[0] or "student").strip().lower()
                    candidate = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in base)[:25] or "student"
                    original = candidate
                    n = 1
                    while candidate in used:
                        candidate = f"{original[:20]}_{n}"
                        n += 1
                    conn.execute(sa.text("UPDATE users SET username=:username WHERE id=:id"), {"username": candidate, "id": user_id})
                    used.add(candidate)
