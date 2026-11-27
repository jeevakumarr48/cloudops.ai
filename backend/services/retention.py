"""Daily retention job that keeps the database small.

Prunes rows nobody needs any more:

* ``user_sessions`` that expired or were revoked more than 7 days ago,
* ``usage_counters`` whose ``window_start`` is more than 40 days old,
* ``snapshots`` fetched more than 40 days ago,
* ``audit_events`` older than 180 days.

``maybe_prune`` runs the job at most once a day (tracked with a usage
counter) and never fails the caller: a database error is logged and the job
is retried the next day.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, cast

from sqlalchemy import CursorResult, delete, or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.models import AuditEvent, Snapshot, UsageCounter, UserSession, utcnow
from core.security import consume

logger = logging.getLogger("cloudops.retention")

SESSION_GRACE = timedelta(days=7)
COUNTER_RETENTION = timedelta(days=40)
SNAPSHOT_RETENTION = timedelta(days=40)
AUDIT_RETENTION = timedelta(days=180)
DAY_SECONDS = 86400


def prune(db: Session, now: Optional[datetime] = None) -> Dict[str, int]:
    """Delete rows past retention and return how many went from each table."""
    now = now or utcnow()
    statements = {
        "user_sessions": delete(UserSession).where(
            or_(
                UserSession.expires_at < now - SESSION_GRACE,
                UserSession.revoked_at < now - SESSION_GRACE,
            )
        ),
        "usage_counters": delete(UsageCounter).where(UsageCounter.window_start < now - COUNTER_RETENTION),
        "snapshots": delete(Snapshot).where(Snapshot.fetched_at < now - SNAPSHOT_RETENTION),
        "audit_events": delete(AuditEvent).where(AuditEvent.created_at < now - AUDIT_RETENTION),
    }
    removed = {
        name: cast(CursorResult, db.execute(stmt)).rowcount or 0
        for name, stmt in statements.items()
    }
    db.commit()
    return removed


def maybe_prune(db: Session) -> Optional[Dict[str, int]]:
    """Run ``prune`` at most once a day. Returns the counts, or ``None`` if
    it already ran today or failed."""
    try:
        if not consume(db, "maintenance:prune", 1, DAY_SECONDS):
            return None
        removed = prune(db)
        logger.info("Retention pruned old rows.", extra={"removed": removed})
        return removed
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Retention pruning failed; will retry tomorrow.")
        return None
