"""Pydantic request and response models for the multi-user API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Literal, Optional, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

Role = Literal["admin", "viewer"]


def as_role(value: str) -> Role:
    """Narrow a stored role string to the API's Role type."""
    if value not in ("admin", "viewer"):
        raise ValueError("Unknown role: %s" % value)
    return cast(Role, value)


def _normalize_email(value: str) -> str:
    value = (value or "").strip().lower()
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address.")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(_Strict):
    email: str
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    display_name: Optional[str] = Field(default=None, max_length=80)

    _email = field_validator("email")(_normalize_email)


class LoginRequest(_Strict):
    email: str
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)

    _email = field_validator("email")(_normalize_email)


class WorkspaceCreate(_Strict):
    name: str = Field(min_length=1, max_length=80)


class MemberAdd(_Strict):
    email: str
    role: Role = "viewer"

    _email = field_validator("email")(_normalize_email)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None


class MembershipOut(BaseModel):
    workspace_id: str
    workspace_name: str
    role: Role


class MeOut(BaseModel):
    user: UserOut
    workspaces: List[MembershipOut]
    # True when the user may view and act on governance data for the
    # deployment's own AWS account (CLOUDOPS_OPERATOR_EMAILS).
    is_operator: bool = False


class WorkspaceOut(BaseModel):
    id: str
    name: str
    role: Role
    created_at: datetime


class MemberOut(BaseModel):
    user_id: str
    email: str
    display_name: Optional[str] = None
    role: Role


class WorkspaceDetailOut(WorkspaceOut):
    members: List[MemberOut]


class AuditEventOut(BaseModel):
    id: str
    action: str
    user_id: Optional[str] = None
    target: Optional[str] = None
    detail: Optional[str] = None
    created_at: datetime
