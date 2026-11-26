"""Operator security views: credential posture and the deployment audit log.

Both are read-only and need a signed-in operator (CLOUDOPS_OPERATOR_EMAILS).
"""

from __future__ import annotations

from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from core import aws_session, config
from core.authz import Principal, require_operator_user
from core.database import get_db
from core.models import AuditEvent, User

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/status")
def status(response: Response, principal: Principal = Depends(require_operator_user)):
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "status": "ok",
        "aws_credentials": aws_session.describe(),
        "session_cookie_secure": config.cookie_secure(),
        "registration_open": config.registration_open(),
        "public_security_findings": config.public_security_findings(),
        "operators_configured": len(config.operator_emails()),
        "changes_to_aws": "none: every AWS call is read-only and nothing is applied automatically",
    }


@router.get("/audit")
def audit_log(
    response: Response,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_operator_user),
    action: Optional[str] = Query(None, max_length=64),
    limit: int = Query(100, ge=1, le=500),
):
    query = (select(AuditEvent, User.email).join(User, AuditEvent.user_id == User.id, isouter=True)
             .order_by(AuditEvent.created_at.desc()).limit(limit))
    if action:
        query = query.where(AuditEvent.action == action.strip())
    rows = db.execute(query).all()
    response.headers["Cache-Control"] = "private, no-store"

    def when(value):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()

    return {"status": "ok", "total": len(rows), "events": [
        {"id": e.id, "action": e.action, "user_email": email, "workspace_id": e.workspace_id, "target": e.target,
         "detail": e.detail, "ip_hash": e.ip_hash, "created_at": when(e.created_at)} for e, email in rows]}
