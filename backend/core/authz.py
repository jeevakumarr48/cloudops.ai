"""Authentication and workspace authorization dependencies.

Every route that touches workspace data must obtain the workspace through
``require_member``/``require_admin``. A user who is not a member receives
404, so workspace ids cannot be probed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import config
from core.database import DatabaseUnavailable, get_db, session_factory
from core.models import ROLE_ADMIN, User, UserSession, Workspace, WorkspaceMember
from core.security import SESSION_COOKIE, resolve_session


@dataclass
class Principal:
    user: User
    session: UserSession


@dataclass
class WorkspaceAccess:
    principal: Principal
    workspace: Workspace
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN


def require_json(request: Request) -> None:
    """CSRF defence for state-changing routes.

    Browsers cannot send ``application/json`` cross-site without a CORS
    preflight, and the session cookie is SameSite=Lax, so requiring JSON
    blocks form-based cross-site submissions.
    """
    content_type = request.headers.get("content-type", "")
    if not content_type.split(";")[0].strip().lower() == "application/json":
        raise HTTPException(status_code=415, detail="Requests must use application/json.")


def current_principal(
    db: Session = Depends(get_db),
    token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> Principal:
    record = resolve_session(db, token)
    if record is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return Principal(user=record.user, session=record)


def _membership(db: Session, workspace_id: str, user_id: str) -> Optional[WorkspaceMember]:
    if not workspace_id or len(workspace_id) > 36:
        return None
    return db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )


def load_workspace(db: Session, principal: Principal, workspace_id: str) -> WorkspaceAccess:
    membership = _membership(db, workspace_id, principal.user.id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceAccess(principal=principal, workspace=membership.workspace, role=membership.role)


def require_member(
    workspace_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> WorkspaceAccess:
    return load_workspace(db, principal, workspace_id)


def require_admin(access: WorkspaceAccess = Depends(require_member)) -> WorkspaceAccess:
    if not access.is_admin:
        raise HTTPException(status_code=403, detail="Workspace admin role required.")
    return access


def require_operator(
    request: Request,
    token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    """Gate for security findings about the deployment's own AWS account.

    Allowed when CLOUDOPS_PUBLIC_SECURITY_FINDINGS=true, or for a signed-in
    user listed in CLOUDOPS_OPERATOR_EMAILS.
    """
    if config.public_security_findings():
        return
    try:
        db = session_factory()()
    except DatabaseUnavailable:
        raise HTTPException(status_code=401, detail="Sign in as a CloudOps AI operator to view this.") from None
    try:
        record = resolve_session(db, token)
        if record is None:
            raise HTTPException(status_code=401, detail="Sign in as a CloudOps AI operator to view this.")
        if record.user.email not in config.operator_emails():
            raise HTTPException(status_code=403, detail="Operator access required.")
    finally:
        db.close()


def require_operator_user(
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
) -> Principal:
    """Writes about the deployment's own account always need a signed-in
    operator, even when findings are publicly readable."""
    if principal.user.email not in config.operator_emails():
        raise HTTPException(status_code=403, detail="Operator access required.")
    return principal
