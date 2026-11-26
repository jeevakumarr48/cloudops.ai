"""Operations views: readiness probe and the operator ops status.

- ``GET /health``          (in main.py) liveness: the process answers.
- ``GET /health/ready``    readiness: the database answers when one is
  configured. Public, no secrets, no AWS call.
- ``GET /api/ops/status``  operator only: build, dependency checks, spend
  budgets, recent governance scans and this instance's request metrics.

Nothing here calls AWS or an AI provider, so loading the ops page is free.
"""

from __future__ import annotations

import time
from datetime import date, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from core import aws_session, config, observability
from core.authz import Principal, require_operator_user
from core.database import DatabaseUnavailable, session_factory
from core.models import ScanRun
from services import cost_store, governance_engine
from services.recommendations import providers, service

router = APIRouter(tags=["operations"])


def _database_check() -> Dict[str, Any]:
    if config.database_url() is None:
        return {"status": "not_configured"}
    started = time.perf_counter()
    try:
        db = session_factory()()
    except DatabaseUnavailable:
        return {"status": "not_configured"}
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    except SQLAlchemyError:
        return {"status": "error"}
    finally:
        db.close()


@router.get("/health/ready")
def ready():
    database = _database_check()
    ok = database["status"] in ("ok", "not_configured")
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ready" if ok else "not_ready", "checks": {"database": database["status"]}},
                        headers={"Cache-Control": "no-store"})


def _recent_scans(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        db = session_factory()()
    except DatabaseUnavailable:
        return []
    try:
        rows = db.scalars(select(ScanRun).where(ScanRun.scope == governance_engine.GLOBAL_SCOPE)
                          .order_by(ScanRun.started_at.desc()).limit(limit)).all()
        return [{"started_at": (r.started_at if r.started_at.tzinfo else r.started_at.replace(tzinfo=timezone.utc)).isoformat(),
                 "duration_ms": r.duration_ms, "finding_count": r.finding_count, "sources": r.sources} for r in rows]
    except SQLAlchemyError:
        return []
    finally:
        db.close()


def _source_health(scans: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in governance_engine.SOURCES:
        runs = [s["sources"][name] for s in scans if name in s["sources"]]
        if not runs:
            continue
        ok = [r for r in runs if r.get("status") == "ok"]
        durations = [r["duration_ms"] for r in runs if isinstance(r.get("duration_ms"), int)]
        out[name] = {"scans": len(runs), "success_rate": round(len(ok) / len(runs), 2),
                     "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
                     "last_status": runs[0].get("status")}
    return out


@router.get("/api/ops/status")
def ops_status(response: Response, principal: Principal = Depends(require_operator_user)):
    scans = _recent_scans()
    cfg = providers.config()
    try:
        db = session_factory()()
    except DatabaseUnavailable:
        db = None
    try:
        ai_used = service.calls_used_today(db)
    except SQLAlchemyError:
        ai_used = None
    finally:
        if db is not None:
            db.close()
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "status": "ok",
        "build": observability.build_info(),
        "checks": {
            "database": _database_check(),
            "aws_credentials": {"mode": aws_session.mode()},
            "ai_provider": cfg.public()["provider"] if cfg else "none",
        },
        "budgets": {
            "cost_explorer_requests_this_month": {"used": cost_store.budget_used(date.today()),
                                                  "limit": config.ce_monthly_call_limit(),
                                                  "note": "Each request is billed by AWS; the cap keeps this line item under $1."},
            "ai_calls_today": {"used": ai_used, "limit": service.daily_call_limit()},
        },
        "scans": {"recent": scans, "by_source": _source_health(scans)},
        "requests": observability.stats.snapshot(),
    }
