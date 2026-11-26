"""AWS credentials for every boto3 client, with optional role-based access.

Modes (``CLOUDOPS_AWS_AUTH``; default ``auto``):

- ``default``      boto3's standard credential chain, unchanged behaviour.
- ``assume_role``  STS AssumeRole into ``CLOUDOPS_AWS_ROLE_ARN`` with the
                   optional ``CLOUDOPS_AWS_EXTERNAL_ID``; the base identity
                   only needs ``sts:AssumeRole``.
- ``oidc``         Vercel OIDC federation: the function's short-lived OIDC
                   token is exchanged with STS AssumeRoleWithWebIdentity for
                   ``CLOUDOPS_AWS_ROLE_ARN``. No AWS keys are stored anywhere.
- ``auto``         ``oidc`` when a role is set and a Vercel OIDC token is
                   available, else ``assume_role`` when a role is set, else
                   ``default``.

Temporary credentials are cached in process until five minutes before they
expire. STS calls are free. Credentials and tokens are never logged or
returned to clients.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import BotoCoreError

_SESSION_NAME = "cloudops-ai-readonly"
_REFRESH_MARGIN_SECONDS = 300
_DURATION_SECONDS = 3600

# Vercel puts the function's OIDC token in the x-vercel-oidc-token request
# header. The token identifies the deployment, not the user, so the middleware
# in main.py keeps the latest one process-wide; that also reaches the worker
# threads S3 discovery uses. AWS verifies the token's signature and the role's
# trust policy, so a forged header cannot grant access.
_latest_token: Optional[str] = None


def remember_oidc_token(token: Optional[str]) -> None:
    global _latest_token
    if token:
        _latest_token = token.strip()

_lock = threading.Lock()
_cached: Dict[str, Any] = {}


class AWSCredentialError(BotoCoreError):
    """Role-based credentials could not be obtained (message is safe to show).

    A BotoCoreError, so every discovery module's existing error handling
    reports the source as unavailable instead of failing the request."""

    fmt = "{message}"

    def __init__(self, message: str):
        super().__init__(message=message)


def role_arn() -> Optional[str]:
    return (os.environ.get("CLOUDOPS_AWS_ROLE_ARN") or "").strip() or None


def _oidc_token() -> Optional[str]:
    if _latest_token:
        return _latest_token
    path = os.environ.get("VERCEL_OIDC_TOKEN_FILE")
    if path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read().strip() or None
        except OSError:
            return None
    return (os.environ.get("VERCEL_OIDC_TOKEN") or "").strip() or None


def mode() -> str:
    configured = (os.environ.get("CLOUDOPS_AWS_AUTH") or "auto").strip().lower()
    if configured in ("default", "assume_role", "oidc"):
        return configured
    if role_arn():
        return "oidc" if _oidc_token() else "assume_role"
    return "default"


def _assume(current_mode: str) -> Dict[str, Any]:
    arn = role_arn()
    if not arn:
        raise AWSCredentialError("CLOUDOPS_AWS_ROLE_ARN is required for role-based access.")
    sts = boto3.client("sts", region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1")
    try:
        if current_mode == "oidc":
            token = _oidc_token()
            if not token:
                raise AWSCredentialError("No Vercel OIDC token is available; enable OIDC federation for the project.")
            response = sts.assume_role_with_web_identity(RoleArn=arn, RoleSessionName=_SESSION_NAME,
                                                         WebIdentityToken=token, DurationSeconds=_DURATION_SECONDS)
        else:
            kwargs = {"RoleArn": arn, "RoleSessionName": _SESSION_NAME, "DurationSeconds": _DURATION_SECONDS}
            external_id = os.environ.get("CLOUDOPS_AWS_EXTERNAL_ID")
            if external_id:
                kwargs["ExternalId"] = external_id
            response = sts.assume_role(**kwargs)
    except AWSCredentialError:
        raise
    except Exception as error:  # noqa: BLE001 - botocore raises many types; never echo details
        code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
        raise AWSCredentialError("Could not assume the CloudOps AI role (%s)." % code) from None
    creds = response["Credentials"]
    return {"key": creds["AccessKeyId"], "secret": creds["SecretAccessKey"], "token": creds["SessionToken"],
            "expires": creds["Expiration"].timestamp()}


def session() -> boto3.Session:
    current_mode = mode()
    if current_mode == "default":
        return boto3.Session()
    with _lock:
        entry = _cached.get(current_mode)
        if entry is None or entry["expires"] - time.time() < _REFRESH_MARGIN_SECONDS:
            entry = _assume(current_mode)
            _cached[current_mode] = entry
    return boto3.Session(aws_access_key_id=entry["key"], aws_secret_access_key=entry["secret"],
                         aws_session_token=entry["token"])


def client(service: str, region_name: Optional[str] = None, config: Any = None):
    """Drop-in replacement for ``boto3.client`` used by all discovery code."""
    kwargs: Dict[str, Any] = {"region_name": region_name}
    if config is not None:
        kwargs["config"] = config
    if mode() == "default":
        return boto3.client(service, **kwargs)  # exactly the original behaviour
    return session().client(service, **kwargs)


def clear_cache() -> None:
    global _latest_token
    with _lock:
        _cached.clear()
        _latest_token = None


def describe() -> Dict[str, Any]:
    """Credential posture for operators. Never includes key material."""
    current_mode = mode()
    info: Dict[str, Any] = {"mode": current_mode, "role_configured": bool(role_arn()),
                            "external_id_configured": bool(os.environ.get("CLOUDOPS_AWS_EXTERNAL_ID"))}
    if current_mode == "default":
        creds = boto3.Session().get_credentials()
        if creds is None:
            info.update(credentials="none", temporary=None, source=None)
        else:
            frozen = creds.get_frozen_credentials()
            info.update(credentials="present", temporary=bool(frozen.token), source=getattr(creds, "method", None))
    else:
        info.update(credentials="role", temporary=True, source=current_mode)
    info["recommendation"] = (
        None if info.get("temporary") else
        "Long-lived access keys are in use. Prefer Vercel OIDC federation (CLOUDOPS_AWS_ROLE_ARN) so no keys are stored."
    )
    return info
