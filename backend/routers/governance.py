"""Unified governance endpoints (findings, summary, status, IaC)."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.authz import Principal, require_json, require_operator, require_operator_user
from core.database import get_db
from core.models import GovernanceFinding, utcnow
from core.security import audit
from services import governance_engine, iac_governance
from services.decision_engine import analyze_iac_changes, normalize_metrics
from services.governance_common import EVIDENCE_STATES, SEVERITY_ORDER
from services.iac_analyzer import IaCPlanError, infracost_status, normalize_infracost, parse_plan

router = APIRouter(prefix="/api/governance", tags=["governance"])

CATEGORIES = ("COST", "UTILIZATION", "SECURITY", "CONFIGURATION", "STORAGE", "AVAILABILITY", "INFRASTRUCTURE", "GOVERNANCE")


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["open", "acknowledged", "accepted_risk", "false_positive"]
    note: Optional[str] = Field(default=None, max_length=500)


def _scan(refresh: bool) -> Dict[str, Any]:
    scan = governance_engine.collect(refresh=refresh)
    findings = governance_engine.sync(scan)
    findings.sort(key=governance_engine.sort_key)
    return {"scanned_at": scan["scanned_at"], "sources": scan["sources"], "findings": findings,
            "evaluations": scan["evaluations"]}


def _validated(value: Optional[str], allowed, name: str) -> Optional[str]:
    if value is None:
        return None
    upper = value.strip().upper() if name != "status" else value.strip().lower()
    if upper not in allowed:
        raise HTTPException(status_code=422, detail="Unknown %s '%s'." % (name, value))
    return upper


@router.get("/findings", dependencies=[Depends(require_operator)])
def list_findings(
    response: Response,
    refresh: bool = False,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    evidence_state: Optional[str] = None,
    resource_type: Optional[str] = None,
    status: Optional[str] = None,
    include_resolved: bool = False,
    limit: int = Query(200, ge=1, le=1000),
):
    category, severity, evidence_state, resource_type, status = validated_filters(
        category, severity, evidence_state, resource_type, status)

    result = _scan(refresh)
    findings = result["findings"]
    if include_resolved or status == "resolved":
        findings = findings + governance_engine.resolved_findings()
    selected = filter_findings(findings, category, severity, evidence_state, resource_type, status)
    response.headers["Cache-Control"] = "private, no-store"
    return {"status": "ok", "scanned_at": result["scanned_at"], "sources": result["sources"],
            "total": len(selected), "findings": selected[:limit]}


def validated_filters(category, severity, evidence_state, resource_type, status):
    return (_validated(category, CATEGORIES, "category"),
            _validated(severity, SEVERITY_ORDER, "severity"),
            _validated(evidence_state, EVIDENCE_STATES, "evidence_state"),
            resource_type.strip().upper() if resource_type else None,
            _validated(status, ("open", "acknowledged", "accepted_risk", "false_positive", "resolved"), "status"))


def filter_findings(findings, category=None, severity=None, evidence_state=None, resource_type=None, status=None):
    def keep(f):
        return ((category is None or f["category"] == category)
                and (severity is None or f["severity"] == severity)
                and (evidence_state is None or f["evidence_state"] == evidence_state)
                and (resource_type is None or f["resource_type"].upper() == resource_type)
                and (status is None or f["lifecycle"]["status"] == status))
    return [f for f in findings if keep(f)]


@router.get("/summary", dependencies=[Depends(require_operator)])
def summary(response: Response, refresh: bool = False):
    result = _scan(refresh)
    response.headers["Cache-Control"] = "private, no-store"
    return summary_payload(result)


def summary_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    active = [f for f in result["findings"] if f["lifecycle"]["status"] not in ("false_positive",)]
    by = lambda key, keys: {k: sum(1 for f in active if f[key] == k) for k in keys}  # noqa: E731
    by_state = dict.fromkeys(EVIDENCE_STATES, 0)
    for evaluation in result["evaluations"]:
        by_state[evaluation["evidence_state"]] += 1
    resource_types = sorted({f["resource_type"] for f in result["evaluations"]})
    return {
        "status": "ok",
        "scanned_at": result["scanned_at"],
        "sources": result["sources"],
        "total_findings": len(active),
        "by_severity": by("severity", SEVERITY_ORDER),
        "by_category": by("category", CATEGORIES),
        "by_resource_type": by("resource_type", resource_types),
        "by_evidence_state": by_state,
        "by_status": {
            s: sum(1 for f in result["findings"] if f["lifecycle"]["status"] == s)
            for s in ("open", "acknowledged", "accepted_risk", "false_positive")
        },
        "top_priorities": [
            {k: f[k] for k in ("finding_id", "rule_id", "resource_type", "resource_id", "severity",
                               "category", "evidence_state", "title", "priority")}
            for f in active[:5]
        ],
        "scoring": {
            "formula": "priority = max(0, (0.45*S + 0.30*X + 0.25*F) * C - P_effort - P_risk)",
            "severity_points": governance_engine.SEVERITY_POINTS,
            "confidence_factor": governance_engine.CONFIDENCE_FACTOR,
            "penalties": governance_engine.PENALTY,
            "financial": "0 unless AWS or Infracost measured a dollar figure; then min(100, 20*log2(1+USD))",
            "exposure": "100 confirmed internet exposure, 60 potential, 0 otherwise",
        },
    }


@router.patch("/findings/{finding_id}", dependencies=[Depends(require_json)])
def update_status(
    finding_id: str,
    body: StatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_operator_user),
):
    row = db.scalar(select(GovernanceFinding).where(
        GovernanceFinding.scope == governance_engine.GLOBAL_SCOPE, GovernanceFinding.finding_id == finding_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    if row.status == "resolved":
        raise HTTPException(status_code=409, detail="Resolved findings reopen automatically if detected again.")
    previous = row.status
    row.status = body.status
    row.status_note = body.note
    row.status_changed_by = principal.user.id
    row.status_changed_at = utcnow()
    audit(db, "finding.status", request=request, user_id=principal.user.id, target=finding_id,
          detail="%s -> %s" % (previous, body.status))
    db.commit()
    return {"status": "ok", "finding_id": finding_id, "finding_status": row.status, "note": row.status_note}


@router.post("/iac")
def analyze_iac(payload: Dict[str, Any] = Body(...)):
    """Terraform plan (+ optional metrics/Infracost) as unified, scored findings.

    Same input as ``POST /api/iac/analyze``; analysis only, nothing applied.
    """
    plan = payload.get("plan")
    if plan is None:
        return JSONResponse(status_code=400, content={"status": "error", "error": "A Terraform plan is required under 'plan'."})
    try:
        changes = parse_plan(plan)["changes"]
    except IaCPlanError as error:
        return JSONResponse(status_code=400, content={"status": "error", "error": str(error)})
    infracost = payload.get("infracost")
    infracost_summary = normalize_infracost(infracost) if infracost is not None else infracost_status()
    legacy = analyze_iac_changes(changes, metrics_by_address=normalize_metrics(payload.get("metrics")),
                                 infracost=infracost_summary)
    findings = iac_governance.to_unified(legacy, infracost_summary)
    for finding in findings:
        finding["priority"] = governance_engine.score(finding)
    findings.sort(key=governance_engine.sort_key)
    return {"status": "ok", "total_findings": len(findings), "findings": findings,
            "infracost": infracost_summary, "changes": len(changes)}
