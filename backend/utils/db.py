"""Database setup for Career AI.

Default: SQLite file (zero-setup local/dev).
Override with DATABASE_URL for Postgres in production, e.g.:
  DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/career_ai
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE = BACKEND_DIR / "data" / "career_ai.db"


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    DEFAULT_SQLITE.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE.as_posix()}"


def create_db_engine(url: str | None = None):
    database_url = url or get_database_url()
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(database_url, future=True, connect_args=connect_args)


_engine = None
_SessionLocal = None


def init_db(url: str | None = None):
    """Create engine/session factory and create tables."""
    global _engine, _SessionLocal
    _engine = create_db_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    # Import models so metadata is registered
    from utils import models  # noqa: F401
    Base.metadata.create_all(bind=_engine)
    return _engine


def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()


def reset_db_for_tests(url: str = "sqlite:///:memory:"):
    """Re-init DB against an isolated URL (used by pytest)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    return init_db(url)
