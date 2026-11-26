"""Workspace and membership endpoints. All are scoped by membership."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.authz import (
    Principal,
    WorkspaceAccess,
    current_principal,
    require_admin,
    require_json,
    require_member,
)
from core.database import get_db
from core.models import ROLE_ADMIN, AuditEvent, User, Workspace, WorkspaceMember
from core.schemas import (
    AuditEventOut,
    MemberAdd,
    MemberOut,
    WorkspaceCreate,
    WorkspaceDetailOut,
    WorkspaceOut,
)
from core.security import audit

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

MAX_WORKSPACES_PER_USER = 10


def _detail(db: Session, access: WorkspaceAccess) -> WorkspaceDetailOut:
    members = db.scalars(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == access.workspace.id)
    ).all()
    return WorkspaceDetailOut(
        id=access.workspace.id,
        name=access.workspace.name,
        role=access.role,
        created_at=access.workspace.created_at,
        members=[
            MemberOut(user_id=m.user_id, email=m.user.email, display_name=m.user.display_name, role=m.role)
            for m in sorted(members, key=lambda m: m.created_at)
        ],
    )


@router.get("", response_model=List[WorkspaceOut])
def list_workspaces(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    rows = db.scalars(
        select(WorkspaceMember).where(WorkspaceMember.user_id == principal.user.id)
    ).all()
    return [
        WorkspaceOut(id=m.workspace.id, name=m.workspace.name, role=m.role, created_at=m.workspace.created_at)
        for m in sorted(rows, key=lambda m: m.workspace.created_at)
    ]


@router.post("", status_code=201, response_model=WorkspaceDetailOut, dependencies=[Depends(require_json)])
def create_workspace(
    body: WorkspaceCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    owned = db.scalars(
        select(WorkspaceMember).where(
            WorkspaceMember.user_id == principal.user.id, WorkspaceMember.role == ROLE_ADMIN
        )
    ).all()
    if len(owned) >= MAX_WORKSPACES_PER_USER:
        raise HTTPException(status_code=409, detail="Workspace limit reached.")
    workspace = Workspace(name=body.name, created_by=principal.user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=principal.user.id, role=ROLE_ADMIN))
    audit(db, "workspace.create", request=request, user_id=principal.user.id, workspace_id=workspace.id)
    db.commit()
    return _detail(db, WorkspaceAccess(principal=principal, workspace=workspace, role=ROLE_ADMIN))


@router.get("/{workspace_id}", response_model=WorkspaceDetailOut)
def get_workspace(access: WorkspaceAccess = Depends(require_member), db: Session = Depends(get_db)):
    return _detail(db, access)


@router.post(
    "/{workspace_id}/members",
    status_code=201,
    response_model=WorkspaceDetailOut,
    dependencies=[Depends(require_json)],
)
def add_member(
    body: MemberAdd,
    request: Request,
    access: WorkspaceAccess = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        # Inviting by email to a not-yet-registered person needs email
        # delivery, which is out of scope for a $0 budget.
        raise HTTPException(status_code=404, detail="No registered user has that email.")
    existing = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == access.workspace.id, WorkspaceMember.user_id == user.id
        )
    )
    if existing is not None:
        if existing.role == ROLE_ADMIN and body.role != ROLE_ADMIN:
            admins = db.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == access.workspace.id,
                    WorkspaceMember.role == ROLE_ADMIN,
                )
            ).all()
            if len(admins) <= 1:
                raise HTTPException(status_code=409, detail="A workspace needs at least one admin.")
        existing.role = body.role
        action = "member.role_change"
    else:
        db.add(WorkspaceMember(workspace_id=access.workspace.id, user_id=user.id, role=body.role))
        action = "member.add"
    audit(
        db, action, request=request, user_id=access.principal.user.id,
        workspace_id=access.workspace.id, target=user.id, detail="role=%s" % body.role,
    )
    db.commit()
    return _detail(db, access)


@router.get("/{workspace_id}/audit", response_model=List[AuditEventOut])
def list_audit(
    access: WorkspaceAccess = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
):
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.workspace_id == access.workspace.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        AuditEventOut(id=r.id, action=r.action, user_id=r.user_id, target=r.target, detail=r.detail, created_at=r.created_at)
        for r in rows
    ]
