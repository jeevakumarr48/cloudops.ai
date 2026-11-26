"""Shared persistence and hard budget for Cost Explorer results.

Cost Explorer bills $0.01 per request. The in-process cache in
``cost_service`` does not survive serverless cold starts, so results are also
stored in the database (shared by every instance) and every billed request is
counted against a monthly cap. When the cap is reached, the most recent real
snapshot is served instead of calling AWS; nothing is ever estimated.

Every function degrades gracefully: if no database is configured or the
database is unreachable, callers fall back to in-process behaviour and the
cost endpoints keep working.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from core import config
from core.database import DatabaseUnavailable, session_factory
from core.models import Snapshot
from core.security import consume_key

logger = logging.getLogger("cloudops.cost_store")

GLOBAL_SCOPE = "global"

# Fallback when no database is configured: per-process only, so it bounds a
# single warm instance rather than the whole deployment.
_local_counts: Dict[str, int] = {}
_local_lock = threading.Lock()


def _session():
    try:
        return session_factory()()
    except DatabaseUnavailable:
        return None


def _month_key(today: date) -> str:
    return "ce-calls:%s" % today.strftime("%Y-%m")


def consume_budget(today: date) -> bool:
    """Count one billed Cost Explorer request. ``False`` = cap reached."""
    limit = config.ce_monthly_call_limit()
    key = _month_key(today)
    db = _session()
    if db is not None:
        try:
            window = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
            return consume_key(db, key, limit, window)
        except SQLAlchemyError:
            logger.warning("Cost budget counter unavailable; using in-process counter.")
            db.rollback()
        finally:
            db.close()
    with _local_lock:
        used = _local_counts.get(key, 0)
        if used >= limit:
            return False
        _local_counts[key] = used + 1
        return True


def load(kind: str, params_key: str, as_of: date) -> Optional[Dict[str, Any]]:
    db = _session()
    if db is None:
        return None
    try:
        row = db.scalar(
            select(Snapshot).where(
                Snapshot.scope == GLOBAL_SCOPE,
                Snapshot.kind == kind,
                Snapshot.params_key == params_key,
                Snapshot.as_of == as_of.isoformat(),
            )
        )
        return dict(row.payload) if row else None
    except SQLAlchemyError:
        logger.warning("Snapshot read failed; continuing without shared cache.")
        return None
    finally:
        db.close()


def latest(kind: str, params_key: str) -> Optional[Dict[str, Any]]:
    db = _session()
    if db is None:
        return None
    try:
        row = db.scalar(
            select(Snapshot)
            .where(
                Snapshot.scope == GLOBAL_SCOPE,
                Snapshot.kind == kind,
                Snapshot.params_key == params_key,
            )
            .order_by(Snapshot.as_of.desc(), Snapshot.fetched_at.desc())
            .limit(1)
        )
        return dict(row.payload) if row else None
    except SQLAlchemyError:
        return None
    finally:
        db.close()


def save(kind: str, params_key: str, as_of: date, payload: Dict[str, Any]) -> None:
    db = _session()
    if db is None:
        return
    try:
        db.add(
            Snapshot(
                scope=GLOBAL_SCOPE,
                kind=kind,
                params_key=params_key,
                as_of=as_of.isoformat(),
                payload=payload,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()  # another instance stored the same day's result first
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Snapshot write failed; result is cached in process only.")
    finally:
        db.close()
