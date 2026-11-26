"""Password hashing, session tokens, counters and audit logging.

Nothing in this module logs or returns a password, token or credential.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core import config
from core.models import AuditEvent, UsageCounter, User, UserSession, utcnow

SESSION_COOKIE = "cloudops_session"
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# Argon2id with the library's current defaults (RFC 9106 low-memory profile).
_hasher = PasswordHasher()
# Verified against when the email is unknown, so response time does not reveal
# whether an account exists.
_DUMMY_HASH = _hasher.hash("cloudops-dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: Optional[str], password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; every stored value is UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def create_session(db: Session, user: User) -> str:
    """Create a session and return the raw token (only ever sent as a cookie)."""
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_digest(token),
            expires_at=utcnow() + timedelta(days=config.session_days()),
        )
    )
    return token


def resolve_session(db: Session, token: Optional[str]) -> Optional[UserSession]:
    if not token or len(token) > 256:
        return None
    record = db.scalar(select(UserSession).where(UserSession.token_hash == token_digest(token)))
    if record is None or record.revoked_at is not None:
        return None
    if _aware(record.expires_at) <= utcnow():
        return None
    if not record.user.is_active:
        return None
    return record


def revoke_session(db: Session, record: UserSession) -> None:
    record.revoked_at = utcnow()


def client_ip(request: Request) -> str:
    """Best-effort client IP. Vercel sets x-forwarded-for / x-real-ip."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def short_hash(value: str) -> str:
    """Non-reversible short identifier for IPs and emails in counters/logs."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def consume(db: Session, name: str, limit: int, window_seconds: int) -> bool:
    """Atomically count one use in a fixed window.

    Returns ``True`` if the use is allowed, ``False`` if the window's limit is
    already reached. Commits its own change so the count survives even if the
    caller's request later fails.
    """
    bucket = int(time.time() // window_seconds)
    return consume_key(
        db,
        ("%s:%d" % (name, bucket))[:128],
        limit,
        datetime.fromtimestamp(bucket * window_seconds, timezone.utc),
    )


def consume_key(db: Session, key: str, limit: int, window_start: datetime) -> bool:
    """Atomically increment ``key`` if it is below ``limit``; see ``consume``."""
    if limit <= 0:
        return False
    for _ in range(3):
        result = cast(CursorResult, db.execute(
            update(UsageCounter)
            .where(UsageCounter.key == key, UsageCounter.count < limit)
            .values(count=UsageCounter.count + 1)
        ))
        if result.rowcount == 1:
            db.commit()
            return True
        if db.get(UsageCounter, key) is not None:
            db.rollback()
            return False
        try:
            db.add(
                UsageCounter(key=key, window_start=window_start, count=1)
            )
            db.commit()
            return True
        except IntegrityError:
            # Another request created the row first; retry the update.
            db.rollback()
    return False


def peek(db: Session, name: str, window_seconds: int) -> int:
    bucket = int(time.time() // window_seconds)
    row = db.get(UsageCounter, ("%s:%d" % (name, bucket))[:128])
    return row.count if row else 0


def audit(
    db: Session,
    action: str,
    *,
    request: Optional[Request] = None,
    user_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    target: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Record an audit event. Callers must never pass secrets in ``detail``."""
    db.add(
        AuditEvent(
            action=action,
            user_id=user_id,
            workspace_id=workspace_id,
            target=target,
            detail=detail,
            ip_hash=short_hash(client_ip(request)) if request is not None else None,
        )
    )
