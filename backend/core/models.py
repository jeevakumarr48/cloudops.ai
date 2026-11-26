"""Database models.

Design rules:

- Every tenant-owned row carries ``workspace_id``; queries for tenant data
  must go through ``core.authz`` helpers that require a verified membership.
- No plaintext secrets: passwords are Argon2id hashes, session tokens are
  stored only as SHA-256 digests, and cloud accounts store an IAM role ARN
  plus ExternalId (not secrets) instead of access keys.
- Types are portable between SQLite (local) and Postgres (production):
  string UUID keys, JSON columns, timezone-aware timestamps.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_VIEWER)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[List["WorkspaceMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    settings: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[List["WorkspaceMember"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default=ROLE_VIEWER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class CloudAccount(Base):
    """An AWS account connected to a workspace through a read-only IAM role.

    Only the role ARN and ExternalId are stored. Neither is a secret; the
    backend obtains short-lived credentials with STS AssumeRole (Phase 3+).
    """

    __tablename__ = "cloud_accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "role_arn", name="uq_workspace_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16), default="aws")
    aws_account_id: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    role_arn: Mapped[str] = mapped_column(String(2048))
    external_id: Mapped[str] = mapped_column(String(128))
    regions: Mapped[List[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="unverified")
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Snapshot(Base):
    """Persisted read-only API results, shared by every server instance.

    ``workspace_id`` is NULL for the deployment's own AWS account (the
    original public dashboard).
    """

    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("scope", "kind", "params_key", "as_of", name="uq_snapshot"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # "global" or the workspace id; a plain column keeps the unique
    # constraint working on databases that treat NULLs as distinct.
    scope: Mapped[str] = mapped_column(String(36), default="global")
    kind: Mapped[str] = mapped_column(String(32))
    params_key: Mapped[str] = mapped_column(String(128))
    as_of: Mapped[str] = mapped_column(String(10))
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageCounter(Base):
    """Fixed-window counters for budgets and rate limits (no Redis needed)."""

    __tablename__ = "usage_counters"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_hash: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


FINDING_STATUSES = ("open", "acknowledged", "accepted_risk", "false_positive", "resolved")


class GovernanceFinding(Base):
    """Lifecycle record for a finding produced by the governance engine.

    ``scope`` is "global" for the deployment's own AWS account or a
    workspace id. The full latest finding is kept in ``payload``; the
    indexed columns exist for filtering.
    """

    __tablename__ = "governance_findings"
    __table_args__ = (UniqueConstraint("scope", "finding_id", name="uq_scope_finding"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(36), default="global", index=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    finding_id: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16))
    rule_id: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(24))
    severity: Mapped[str] = mapped_column(String(12))
    evidence_state: Mapped[str] = mapped_column(String(24))
    priority_score: Mapped[float] = mapped_column(default=0.0)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="open")
    status_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status_changed_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    times_reopened: Mapped[int] = mapped_column(Integer, default=0)
    first_detected: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_detected: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
