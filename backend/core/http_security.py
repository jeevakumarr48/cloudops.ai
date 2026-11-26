"""Request-level security: origin check, security headers, request ids and a
consistent error envelope.

Error envelope (every error response from FastAPI exceptions)::

    {"status": "error", "error": "<message>", "code": "<code>",
     "request_id": "<id>", "detail": <original detail>}

``status`` and ``error`` match the shape the original endpoints already use
for unavailable data, and ``detail`` keeps FastAPI's field so existing
clients keep working. Every response carries an ``X-Request-ID`` header.
"""

from __future__ import annotations

import logging
import secrets
from typing import Iterable, Set
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core import aws_session, config
from core.security import SESSION_COOKIE

logger = logging.getLogger("cloudops.http")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
         409: "conflict", 415: "unsupported_media_type", 422: "validation_error", 429: "rate_limited",
         500: "internal_error", 503: "unavailable"}
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return "%s://%s" % (parts.scheme, parts.netloc) if parts.scheme and parts.netloc else ""


def _envelope(request: Request, status_code: int, message: str, detail=None, code: str | None = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = {"status": "error", "error": message, "code": code or CODES.get(status_code, "error"),
            "request_id": request_id, "detail": detail if detail is not None else message}
    return JSONResponse(status_code=status_code, content=body)


def install(app: FastAPI, allowed_origins: Iterable[str]) -> None:
    allowed: Set[str] = {o.rstrip("/") for o in allowed_origins if o}

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        request.state.request_id = secrets.token_hex(8)
        aws_session.remember_oidc_token(request.headers.get("x-vercel-oidc-token"))

        # CSRF defence in depth (with SameSite=Lax and require_json): a
        # state-changing request that carries the session cookie must come
        # from an allowed origin or from this API's own origin.
        if request.method in UNSAFE_METHODS and request.cookies.get(SESSION_COOKIE):
            origin = (request.headers.get("origin") or "").rstrip("/")
            own = _origin_of(str(request.base_url)).rstrip("/")
            if origin and origin != "null":
                ok = origin in allowed or origin == own
            else:
                ok = request.headers.get("sec-fetch-site", "same-origin") in ("same-origin", "same-site", "none")
            if not ok:
                response = _envelope(request, 403, "This request came from a site that is not allowed.",
                                     code="origin_not_allowed")
                response.headers["X-Request-ID"] = request.state.request_id
                return response

        response = await call_next(request)
        headers = response.headers
        headers["X-Request-ID"] = request.state.request_id
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith(_DOCS_PATHS):
            headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if config.cookie_secure():
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith("/api/auth"):
            headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else CODES.get(exc.status_code, "error").replace("_", " ")
        response = _envelope(request, exc.status_code, message, detail=exc.detail)
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return _envelope(request, 422, "The request was not valid.", detail=errors)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled error (request %s)", getattr(request.state, "request_id", "?"))
        return _envelope(request, 500, "Internal error. Quote the request id when reporting it.")
