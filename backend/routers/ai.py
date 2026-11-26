"""Recommendation endpoints (advisory only; nothing here changes AWS).

- ``GET  /api/ai/recommendations``  deterministic, cached per evidence hash;
  never calls an AI provider, so dashboard refreshes cost nothing.
- ``POST /api/ai/analyze``          user-triggered AI rewrite of up to 10
  findings, validated, with a daily provider-call cap.
- ``POST /api/ai/recommendations/{id}/feedback``  record a human decision.
- ``GET  /api/ai/status``           provider and budget status (no secrets).
"""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from core.authz import Principal, require_json, require_operator, require_operator_user
from core.database import DatabaseUnavailable, get_db, session_factory
from core.security import audit, consume
from services import governance_engine
from services.recommendations import providers, service

router = APIRouter(prefix="/api/ai", tags=["recommendations"])
SCOPE = governance_engine.GLOBAL_SCOPE


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_ids: Optional[List[str]] = Field(default=None, max_length=service.MAX_ANALYZE)
    limit: int = Field(default=5, ge=1, le=service.MAX_ANALYZE)


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["accepted", "rejected", "remediation_in_progress", "remediated_pending_verification"]
    note: Optional[str] = Field(default=None, max_length=500)


def _findings(refresh: bool):
    scan = governance_engine.collect(refresh=refresh)
    return scan, governance_engine.sync(scan)


def _optional_db():
    try:
        return session_factory()()
    except DatabaseUnavailable:
        return None


@router.get("/recommendations", dependencies=[Depends(require_operator)])
def list_recommendations(response: Response, refresh: bool = False):
    scan, findings = _findings(refresh)
    db = _optional_db()
    try:
        result = service.list_recommendations(findings, db, SCOPE)
    finally:
        if db is not None:
            db.close()
    response.headers["Cache-Control"] = "private, no-store"
    return {"status": "ok", "scanned_at": scan["scanned_at"], "sources": scan["sources"],
            "persisted": result["persisted"], "summary": result["summary"],
            "total": len(result["recommendations"]), "recommendations": result["recommendations"]}


@router.get("/status", dependencies=[Depends(require_operator)])
def status(response: Response):
    cfg = providers.config()
    db = _optional_db()
    try:
        used = service.calls_used_today(db)
    finally:
        if db is not None:
            db.close()
    response.headers["Cache-Control"] = "private, no-store"
    return {"status": "ok",
            "provider": cfg.public() if cfg else {"provider": "none", "model": None, "local": False,
                                                  "api_key_configured": False},
            "daily_call_limit": service.daily_call_limit(), "calls_used_today": used,
            "max_findings_per_analyze": service.MAX_ANALYZE}


@router.post("/analyze", dependencies=[Depends(require_json)])
def analyze(body: AnalyzeRequest, request: Request, response: Response, db: Session = Depends(get_db),
            principal: Principal = Depends(require_operator_user)):
    if not consume(db, "ai_analyze:%s" % principal.user.id, 10, 3600):
        raise HTTPException(status_code=429, detail="Too many analysis requests; try again within the hour.")
    _, findings = _findings(False)
    result = service.analyze(findings, db, SCOPE, finding_ids=body.finding_ids, limit=body.limit)
    audit(db, "ai.analyze", request=request, user_id=principal.user.id,
          detail="%d finding(s), %d provider call(s)" % (len(result["results"]), result["provider_calls"]))
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return {"status": "ok", **result}


@router.post("/recommendations/{recommendation_id}/feedback", dependencies=[Depends(require_json)])
def feedback(recommendation_id: str, body: FeedbackRequest, request: Request, db: Session = Depends(get_db),
             principal: Principal = Depends(require_operator_user)):
    row = service.record_feedback(db, SCOPE, recommendation_id, body.decision, body.note, principal.user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    audit(db, "recommendation.feedback", request=request, user_id=principal.user.id,
          target=recommendation_id, detail=body.decision)
    db.commit()
    return {"status": "ok", "recommendation_id": recommendation_id, "decision": body.decision, "note": body.note,
            "changes_applied": False}
