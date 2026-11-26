"""Runtime configuration read from environment variables only.

No secret value is ever logged or returned by this module.
"""

from __future__ import annotations

import os
from typing import Optional

LOCAL_SQLITE_URL = "sqlite:///./cloudops.db"


def is_serverless() -> bool:
    """True on Vercel, where the function filesystem is ephemeral."""
    return bool(os.environ.get("VERCEL"))


def database_url() -> Optional[str]:
    """Return the database URL, or ``None`` when persistence is unavailable.

    Locally a SQLite file is used by default. On Vercel a SQLite file would be
    lost on every cold start, so a ``DATABASE_URL`` (for example a Neon
    Postgres connection string) is required there; without one, the
    multi-user features report themselves as unavailable and the original
    endpoints keep working.
    """
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        # Neon and other providers hand out postgres:// URLs; SQLAlchemy
        # needs an explicit driver.
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url
    if is_serverless():
        return None
    return LOCAL_SQLITE_URL


def cookie_secure() -> bool:
    """Session cookies are Secure unless explicitly disabled for local HTTP."""
    return os.environ.get("CLOUDOPS_COOKIE_SECURE", "true").strip().lower() != "false"


def session_days() -> int:
    return int(os.environ.get("CLOUDOPS_SESSION_DAYS", "7"))


def registration_open() -> bool:
    """Self-registration can be closed with CLOUDOPS_REGISTRATION_OPEN=false."""
    return os.environ.get("CLOUDOPS_REGISTRATION_OPEN", "true").strip().lower() != "false"


def ce_monthly_call_limit() -> int:
    """Hard cap on billed Cost Explorer requests per calendar month (UTC).

    Each request costs $0.01, so the default of 75 caps that line item at
    $0.75 per month, leaving headroom under the project's $1 ceiling.
    """
    return int(os.environ.get("CLOUDOPS_CE_MONTHLY_CALL_LIMIT", "75"))
