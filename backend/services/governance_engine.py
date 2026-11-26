"""Unified governance engine.

Collects evidence from every source, runs the deterministic rules, scores
findings with a documented formula, and keeps a lifecycle record for each
finding in the database (first/last detected, status, auto-resolve when the
condition disappears, reopen when it returns).

A source that fails is reported as unavailable and its existing findings are
left untouched: an outage never "resolves" anything.

Priority score (0-100, deterministic; the AI layer never changes it)::

    impact   = 0.45*S + 0.30*X + 0.25*F
    priority = max(0, impact*C - P_effort - P_risk)

    S  severity:  CRITICAL 100, HIGH 75, MEDIUM 50, LOW 25, INFO 0
    X  exposure:  100 confirmed internet exposure, 60 potential exposure, else 0
    F  financial: 0 unless a dollar figure measured by AWS or Infracost exists;
                  then min(100, 20*log2(1 + USD))
    C  confidence: CONFIRMED 1.0, POTENTIAL 0.7, INSUFFICIENT_EVIDENCE 0.3
    P_effort, P_risk: 0 / 5 / 10 for low / medium / high
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from aws_client import AWSAccessError, create_ec2_client, discover_ec2_instances
from core.database import DatabaseUnavailable, session_factory
from core.models import GovernanceFinding, utcnow
from services import cost_governance, ec2_governance, rds_governance, s3_governance
from services.aws_metrics import MetricsUnavailableError, get_ec2_metrics
from services.cost_service import CostServiceError, get_cost_summary
from services.governance_common import (
    CONFIRMED,
    FINDING_STATES,
    INSUFFICIENT_EVIDENCE,
    POTENTIAL,
    SEVERITY_ORDER,
)
from services.rds_discovery import RDSAccessError, discover_rds_instances
from services.s3_discovery import S3AccessError, discover_s3_buckets

logger = logging.getLogger("cloudops.governance")

GLOBAL_SCOPE = "global"
SOURCES = ("ec2", "s3", "rds", "cost")
SOURCE_BY_TYPE = {"EC2": "ec2", "S3": "s3", "RDS": "rds", "ACCOUNT": "cost"}

SEVERITY_POINTS = {"CRITICAL": 100, "HIGH": 75, "MEDIUM": 50, "LOW": 25, "INFO": 0}
CONFIDENCE_FACTOR = {CONFIRMED: 1.0, POTENTIAL: 0.7, INSUFFICIENT_EVIDENCE: 0.3}
PENALTY = {"low": 0, "medium": 5, "high": 10}
EXPOSURE_RULES = {"S3_PUBLIC_POLICY", "S3_PUBLIC_ACL", "RDS_PUBLIC_ACCESS", "EC2_OPEN_ADMIN_PORTS", "S3_BLOCK_PUBLIC_ACCESS"}

# Remediation effort and operational risk of the *recommended action*.
RULE_META: Dict[str, Dict[str, str]] = {
    "EC2_OPEN_ADMIN_PORTS": {"effort": "low", "risk": "low"},
    "EC2_STOPPED_INSTANCE": {"effort": "low", "risk": "medium"},
    "EC2_LOW_UTILIZATION": {"effort": "medium", "risk": "medium"},
    "EC2_MISSING_OWNER_TAG": {"effort": "low", "risk": "low"},
    "EC2_MISSING_ENVIRONMENT_TAG": {"effort": "low", "risk": "low"},
    "S3_PUBLIC_POLICY": {"effort": "low", "risk": "medium"},
    "S3_PUBLIC_ACL": {"effort": "low", "risk": "medium"},
    "S3_BLOCK_PUBLIC_ACCESS": {"effort": "low", "risk": "medium"},
    "S3_DEFAULT_ENCRYPTION": {"effort": "low", "risk": "low"},
    "S3_VERSIONING": {"effort": "low", "risk": "low"},
    "S3_LIFECYCLE": {"effort": "medium", "risk": "medium"},
    "S3_ACCESS_LOGGING": {"effort": "low", "risk": "low"},
    "RDS_PUBLIC_ACCESS": {"effort": "medium", "risk": "medium"},
    "RDS_STORAGE_ENCRYPTION": {"effort": "high", "risk": "high"},
    "RDS_BACKUP_RETENTION": {"effort": "low", "risk": "low"},
    "RDS_MULTI_AZ": {"effort": "medium", "risk": "medium"},
    "RDS_DELETION_PROTECTION": {"effort": "low", "risk": "low"},
    "RDS_LOW_UTILIZATION": {"effort": "medium", "risk": "high"},
    "RDS_STORAGE_HEADROOM": {"effort": "medium", "risk": "medium"},
    "RDS_GP2_STORAGE": {"effort": "low", "risk": "low"},
    "COST_WEEKLY_INCREASE": {"effort": "medium", "risk": "low"},
}
_RESIZE_RULES = {"EC2_LOW_UTILIZATION", "RDS_LOW_UTILIZATION"}


def score(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic priority with every input exposed for transparency."""
    state = finding["evidence_state"]
    s = SEVERITY_POINTS.get(finding["severity"], 0)
    if finding["rule_id"] in EXPOSURE_RULES:
        x = 100 if state == CONFIRMED and finding["severity"] in ("CRITICAL", "HIGH") else (60 if state in (CONFIRMED, POTENTIAL) else 0)
    else:
        x = 0
    usd = finding.get("measured_usd")
    f = min(100.0, 20 * math.log2(1 + usd)) if isinstance(usd, (int, float)) and usd > 0 else 0.0
    c = CONFIDENCE_FACTOR.get(state, 0.0)
    meta = RULE_META.get(finding["rule_id"], {"effort": "medium", "risk": "medium"})
    risk = meta["risk"]
    if finding["rule_id"] in _RESIZE_RULES and "production" in (finding.get("description") or ""):
        risk = "high"
    impact = 0.45 * s + 0.30 * x + 0.25 * f
    priority = max(0.0, impact * c - PENALTY[meta["effort"]] - PENALTY[risk])
    return {
        "score": round(priority, 1),
        "inputs": {"severity": s, "exposure": x, "financial": round(f, 1), "confidence": c,
                   "effort": meta["effort"], "risk": risk},
        "formula": "max(0, (0.45*S + 0.30*X + 0.25*F) * C - P_effort - P_risk)",
    }


def _run(name: str, fn: Callable[[], List[Dict[str, Any]]], expected: Tuple[type, ...]) -> Dict[str, Any]:
    try:
        evaluations = fn()
        return {"status": "ok", "error": None, "evaluations": evaluations}
    except expected as error:
        return {"status": "unavailable", "error": str(error), "evaluations": []}
    except Exception:  # noqa: BLE001 - one broken source must not break the rest
        logger.exception("Governance source %s failed", name)
        return {"status": "unavailable", "error": "Unexpected error while collecting %s data." % name, "evaluations": []}


def _ec2_source(refresh: bool) -> List[Dict[str, Any]]:
    instances = discover_ec2_instances()
    ids = [i.get("InstanceId") for i in instances if i.get("InstanceId")]
    metrics_status = "ok"
    by_id: Dict[str, Dict] = {}
    try:
        by_id = {m["instance_id"]: m for m in get_ec2_metrics(ids, hours=ec2_governance.METRIC_HOURS)}
    except MetricsUnavailableError:
        metrics_status = "error"
    exposure = ec2_governance.admin_port_exposure(create_ec2_client(), instances) if instances else {}
    out: List[Dict[str, Any]] = []
    for instance in instances:
        out.extend(ec2_governance.evaluate_instance(
            instance, by_id.get(instance.get("InstanceId")), metrics_status, exposure.get(instance.get("InstanceId"))
        ))
    return out


def _s3_source(refresh: bool) -> List[Dict[str, Any]]:
    inventory = discover_s3_buckets(refresh=refresh)
    out: List[Dict[str, Any]] = []
    for bucket in inventory["buckets"]:
        out.extend(s3_governance.evaluate_bucket(bucket, inventory["account_public_access_block"]))
    return out


def _rds_source(refresh: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for db in discover_rds_instances(refresh=refresh)["instances"]:
        out.extend(rds_governance.evaluate_instance(db))
    return out


def _cost_source(refresh: bool) -> List[Dict[str, Any]]:
    return cost_governance.evaluate_costs(get_cost_summary(period="daily"))


def collect(refresh: bool = False, sources: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run every (or selected) source and return evaluations with scores."""
    runners = {
        "ec2": (_ec2_source, (AWSAccessError,)),
        "s3": (_s3_source, (S3AccessError,)),
        "rds": (_rds_source, (RDSAccessError,)),
        "cost": (_cost_source, (CostServiceError,)),
    }
    selected = [s for s in (sources or SOURCES) if s in runners]
    results = {name: _run(name, lambda fn=runners[name][0]: fn(refresh), runners[name][1]) for name in selected}
    evaluations: List[Dict[str, Any]] = []
    for name, result in results.items():
        for evaluation in result["evaluations"]:
            evaluation["source"] = name
            if evaluation["evidence_state"] in FINDING_STATES:
                evaluation["priority"] = score(evaluation)
            evaluations.append(evaluation)
    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "sources": {name: {"status": r["status"], "error": r["error"],
                           "evaluated_rules": len(r["evaluations"])} for name, r in results.items()},
        "evaluations": evaluations,
    }


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _lifecycle(row: Optional[GovernanceFinding], now: datetime, persisted: bool) -> Dict[str, Any]:
    if row is None:
        return {"status": "open", "first_detected": now.isoformat(), "last_detected": now.isoformat(),
                "resolved_at": None, "times_reopened": 0, "status_note": None, "persisted": persisted}
    return {
        "status": row.status,
        "first_detected": _aware(row.first_detected).isoformat(),
        "last_detected": _aware(row.last_detected).isoformat(),
        "resolved_at": _aware(row.resolved_at).isoformat() if row.resolved_at else None,
        "times_reopened": row.times_reopened,
        "status_note": row.status_note,
        "persisted": persisted,
    }


def sync(scan: Dict[str, Any], scope: str = GLOBAL_SCOPE) -> List[Dict[str, Any]]:
    """Persist findings and lifecycle; return findings with lifecycle fields.

    Without a database the findings are returned with ``persisted: false``.
    """
    now = utcnow()
    current = [e for e in scan["evaluations"] if e["evidence_state"] in FINDING_STATES]
    ok_sources = {name for name, s in scan["sources"].items() if s["status"] == "ok"}
    try:
        db = session_factory()()
    except DatabaseUnavailable:
        db = None
    if db is None:
        for finding in current:
            finding["lifecycle"] = _lifecycle(None, now, False)
        return current
    try:
        rows = {r.finding_id: r for r in db.scalars(select(GovernanceFinding).where(GovernanceFinding.scope == scope))}
        seen = set()
        for finding in current:
            seen.add(finding["finding_id"])
            row = rows.get(finding["finding_id"])
            if row is None:
                row = GovernanceFinding(scope=scope, finding_id=finding["finding_id"], first_detected=now,
                                        status="open", times_reopened=0)
                db.add(row)
                rows[finding["finding_id"]] = row
            elif row.status == "resolved":
                row.status, row.resolved_at = "open", None
                row.times_reopened = (row.times_reopened or 0) + 1
            row.source = finding["source"]
            row.rule_id = finding["rule_id"]
            row.resource_type = finding["resource_type"]
            row.resource_id = str(finding["resource_id"])[:255]
            row.category = finding["category"]
            row.severity = finding["severity"]
            row.evidence_state = finding["evidence_state"]
            row.priority_score = finding["priority"]["score"]
            row.payload = {k: v for k, v in finding.items() if k != "lifecycle"}
            row.last_detected = now
        # Revalidation: a finding from a source that scanned successfully and
        # no longer reports it is resolved automatically.
        for finding_id, row in rows.items():
            if finding_id not in seen and row.source in ok_sources and row.status != "resolved":
                row.status, row.resolved_at = "resolved", now
                row.status_note = "Condition no longer detected on %s." % now.date().isoformat()
        db.commit()
        for finding in current:
            finding["lifecycle"] = _lifecycle(rows[finding["finding_id"]], now, True)
        return current
    except SQLAlchemyError:
        db.rollback()
        logger.warning("Finding lifecycle could not be persisted; returning unpersisted findings.")
        for finding in current:
            finding["lifecycle"] = _lifecycle(None, now, False)
        return current
    finally:
        db.close()


def resolved_findings(scope: str = GLOBAL_SCOPE, limit: int = 50) -> List[Dict[str, Any]]:
    try:
        db = session_factory()()
    except DatabaseUnavailable:
        return []
    try:
        rows = db.scalars(
            select(GovernanceFinding)
            .where(GovernanceFinding.scope == scope, GovernanceFinding.status == "resolved")
            .order_by(GovernanceFinding.resolved_at.desc())
            .limit(limit)
        ).all()
        return [dict(r.payload, lifecycle=_lifecycle(r, utcnow(), True)) for r in rows]
    except SQLAlchemyError:
        return []
    finally:
        db.close()


def sort_key(finding: Dict[str, Any]):
    return (-finding.get("priority", {}).get("score", 0), SEVERITY_ORDER.get(finding["severity"], 9), finding["rule_id"])
