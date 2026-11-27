"""Public, read-only demo endpoints (sample data only).

These mirror the read endpoints of the governance console so the frontend can
show the same pages without an account. They never read AWS, never write to
the database and never call an AI provider. Every response carries
``demo: true`` and a ``sample_data_notice``.

- ``GET /api/demo/governance/summary``
- ``GET /api/demo/governance/findings``
- ``GET /api/demo/ai/recommendations``
- ``GET /api/demo/ai/status``
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from routers.governance import filter_findings, summary_payload, validated_filters
from services import demo
from services.recommendations import service

router = APIRouter(prefix="/api/demo", tags=["demo"])
_CACHE = "public, max-age=300"


def _require_enabled() -> None:
    if not demo.enabled():
        raise HTTPException(status_code=404, detail="The demo is turned off on this deployment.")


def _label(payload: dict) -> dict:
    return dict(payload, demo=True, sample_data_notice=demo.LABEL)


@router.get("/governance/summary", dependencies=[Depends(_require_enabled)])
def summary(response: Response):
    response.headers["Cache-Control"] = _CACHE
    return _label(summary_payload(demo.scan()))


@router.get("/governance/findings", dependencies=[Depends(_require_enabled)])
def findings(
    response: Response,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    evidence_state: Optional[str] = None,
    resource_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    filters = validated_filters(category, severity, evidence_state, resource_type, status)
    scan = demo.scan()
    selected = filter_findings(scan["findings"], *filters)
    response.headers["Cache-Control"] = _CACHE
    return _label({"status": "ok", "scanned_at": scan["scanned_at"], "sources": scan["sources"],
                   "total": len(selected), "findings": selected[:limit]})


@router.get("/ai/recommendations", dependencies=[Depends(_require_enabled)])
def recommendations(response: Response):
    scan = demo.scan()
    # No database: templates only, no feedback, no AI provider call.
    result = service.list_recommendations(scan["findings"], None, demo.SCOPE)
    response.headers["Cache-Control"] = _CACHE
    return _label({"status": "ok", "scanned_at": scan["scanned_at"], "sources": scan["sources"],
                   "persisted": False, "summary": result["summary"], "total": len(result["recommendations"]),
                   "recommendations": result["recommendations"], "plan": result["plan"]})


@router.get("/ai/status", dependencies=[Depends(_require_enabled)])
def status(response: Response):
    response.headers["Cache-Control"] = _CACHE
    return _label({"status": "ok",
                   "provider": {"provider": "none", "model": None, "local": False, "api_key_configured": False},
                   "daily_call_limit": 0, "calls_used_today": None,
                   "max_findings_per_analyze": 0})
