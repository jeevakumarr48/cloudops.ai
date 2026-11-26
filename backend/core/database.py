"""SQLAlchemy engine and session handling.

The engine is created lazily so importing the API never opens a connection
and the original endpoints work without any database.
"""

from __future__ import annotations

import threading
from typing import Iterator, Optional

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from core import config


class Base(DeclarativeBase):
    pass


_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None
_lock = threading.Lock()


class DatabaseUnavailable(RuntimeError):
    """Raised when persistence is not configured for this deployment."""


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    # Serverless functions should not hold pooled connections between
    # invocations; Neon's pooled endpoint does the pooling instead.
    # prepare_threshold=None disables server-side prepared statements, which
    # transaction-mode poolers such as Neon's pooled endpoint do not support.
    return create_engine(
        url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None, "connect_timeout": 10},
    )


def configure(engine: Engine) -> None:
    """Install an explicit engine (used by tests and scripts)."""
    global _engine, _session_factory
    with _lock:
        _engine = engine
        _session_factory = sessionmaker(bind=engine, expire_on_commit=False)


def reset() -> None:
    global _engine, _session_factory
    with _lock:
        _engine = None
        _session_factory = None


def _upgrade_local_sqlite(engine: Engine) -> None:
    """Apply migrations automatically for the local SQLite file only.

    Production (Postgres) is migrated explicitly with ``alembic upgrade head``
    so schema changes never happen as a side effect of a request.
    """
    import os

    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    url = config.database_url()
    if url is None:
        raise DatabaseUnavailable("Persistence is not configured for this deployment.")
    with _lock:
        if _engine is None:
            engine = _build_engine(url)
            if url.startswith("sqlite"):
                _upgrade_local_sqlite(engine)
            _engine = engine
            _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker:
    get_engine()
    if _session_factory is None:  # get_engine() raises DatabaseUnavailable before this can happen
        raise DatabaseUnavailable("No database is configured.")
    return _session_factory


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session, or 503 when no DB exists."""
    try:
        factory = session_factory()
    except DatabaseUnavailable:
        raise HTTPException(
            status_code=503,
            detail="Accounts and workspaces are not available on this deployment yet.",
        ) from None
    db = factory()
    try:
        yield db
    finally:
        db.close()
