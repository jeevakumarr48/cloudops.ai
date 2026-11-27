"""Registration, login, logout and current-user endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core import config
from core.authz import Principal, current_principal, require_json
from core.database import get_db
from core.models import ROLE_ADMIN, User, Workspace, WorkspaceMember
from core.schemas import LoginRequest, MembershipOut, MeOut, RegisterRequest, UserOut, as_role
from core.security import (
    SESSION_COOKIE,
    audit,
    client_ip,
    consume,
    create_session,
    hash_password,
    needs_rehash,
    peek,
    revoke_session,
    short_hash,
    verify_password,
)
from services import retention

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Rate limits (fixed windows, counted in the database so they hold across
# serverless instances).
LOGIN_ATTEMPTS_PER_IP = 30
LOGIN_FAILURES_PER_EMAIL = 5
LOGIN_WINDOW_SECONDS = 15 * 60
REGISTRATIONS_PER_IP = 5
REGISTRATION_WINDOW_SECONDS = 60 * 60

_TOO_MANY = "Too many attempts. Try again later."


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=config.session_days() * 86400,
        httponly=True,
        secure=config.cookie_secure(),
        samesite="lax",
        path="/",
    )


def _me(db: Session, user: User) -> MeOut:
    rows = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).all()
    return MeOut(
        user=UserOut(id=user.id, email=user.email, display_name=user.display_name),
        workspaces=[
            MembershipOut(workspace_id=m.workspace_id, workspace_name=m.workspace.name, role=as_role(m.role))
            for m in sorted(rows, key=lambda m: m.workspace.created_at)
        ],
        is_operator=user.email in config.operator_emails(),
    )


@router.post("/register", status_code=201, response_model=MeOut, dependencies=[Depends(require_json)])
def register(
    body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)
):
    if not config.registration_open():
        raise HTTPException(status_code=403, detail="Registration is closed.")
    ip = short_hash(client_ip(request))
    if not consume(db, "register:ip:%s" % ip, REGISTRATIONS_PER_IP, REGISTRATION_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail=_TOO_MANY)
    # Keeps a public deployment inside the free database tier. Operators can
    # always register, so a full deployment never locks out its owner.
    if body.email not in config.operator_emails() and (
        db.scalar(select(func.count()).select_from(User)) or 0
    ) >= config.max_users():
        raise HTTPException(status_code=403, detail="This deployment has reached its account limit.")

    user = User(
        email=body.email,
        display_name=body.display_name or None,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from None

    # Every new user gets a personal workspace they administer.
    workspace = Workspace(name="%s's workspace" % (body.display_name or body.email.split("@")[0]), created_by=user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=ROLE_ADMIN))
    audit(db, "user.register", request=request, user_id=user.id, workspace_id=workspace.id)
    token = create_session(db, user)
    db.commit()
    _set_session_cookie(response, token)
    return _me(db, user)


@router.post("/login", response_model=MeOut, dependencies=[Depends(require_json)])
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = short_hash(client_ip(request))
    email_key = "login-fail:email:%s" % short_hash(body.email)
    if not consume(db, "login:ip:%s" % ip, LOGIN_ATTEMPTS_PER_IP, LOGIN_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail=_TOO_MANY)
    if peek(db, email_key, LOGIN_WINDOW_SECONDS) >= LOGIN_FAILURES_PER_EMAIL:
        raise HTTPException(status_code=429, detail=_TOO_MANY)

    user = db.scalar(select(User).where(User.email == body.email))
    valid = verify_password(user.password_hash if user else None, body.password)
    if user is None or not valid or not user.is_active:
        consume(db, email_key, LOGIN_FAILURES_PER_EMAIL, LOGIN_WINDOW_SECONDS)
        audit(db, "user.login_failed", request=request, user_id=user.id if user else None)
        db.commit()
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    audit(db, "user.login", request=request, user_id=user.id)
    token = create_session(db, user)
    db.commit()
    retention.maybe_prune(db)
    _set_session_cookie(response, token)
    return _me(db, user)


@router.post("/logout", status_code=204, dependencies=[Depends(require_json)])
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    revoke_session(db, principal.session)
    audit(db, "user.logout", request=request, user_id=principal.user.id)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", secure=config.cookie_secure(), httponly=True, samesite="lax")
    response.status_code = 204
    return response


@router.get("/me", response_model=MeOut)
def me(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    return _me(db, principal.user)
