"""Recommendation service: templates, cache, optional AI rewrite, feedback.

- ``list_recommendations`` returns deterministic recommendations for the
  current findings. It never calls an AI provider. When a database exists,
  each recommendation is stored once per evidence hash, so a validated AI
  rewrite produced earlier is reused for as long as the evidence is unchanged.
- ``analyze`` is user-triggered. It rewrites at most ``MAX_ANALYZE`` findings,
  skips any whose evidence already has an AI rewrite, and spends at most
  ``CLOUDOPS_AI_DAILY_CALL_LIMIT`` provider calls per UTC day (counted in the
  database, so the cap holds across serverless instances).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.models import RecommendationFeedback, RecommendationRecord, utcnow
from core.security import consume_key
from services.governance_common import SEVERITY_ORDER
from services.recommendations import fix_commands, providers, templates, validator
from services.recommendations.context import build_bundles
from services.recommendations.plan import fix_first_plan
from services.recommendations.schema import LLMRewrite, Recommendation

logger = logging.getLogger("cloudops.recommendations")

MAX_ANALYZE = 10
_REWRITE_FIELDS = ("problem", "why_it_matters", "suggested_action", "expected_benefits",
                   "potential_risks", "correlation_note")


def daily_call_limit() -> int:
    return int(os.environ.get("CLOUDOPS_AI_DAILY_CALL_LIMIT", "20"))


def _today_key() -> tuple:
    today = datetime.now(timezone.utc).date()
    return "ai_llm_calls:%s" % today.isoformat(), datetime.combine(today, time.min, tzinfo=timezone.utc)


def calls_used_today(db: Optional[Session]) -> Optional[int]:
    if db is None:
        return None
    from core.models import UsageCounter
    row = db.get(UsageCounter, _today_key()[0])
    return row.count if row else 0


def _latest_feedback(db: Session, scope: str, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    rows = db.scalars(
        select(RecommendationFeedback)
        .where(RecommendationFeedback.scope == scope, RecommendationFeedback.recommendation_id.in_(ids))
        .order_by(RecommendationFeedback.created_at.desc())
    ).all()
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        latest.setdefault(row.recommendation_id, {
            "decision": row.decision, "note": row.note,
            "recorded_at": (row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)).isoformat(),
        })
    return latest


def _cached(db: Session, scope: str, bundles: List[Dict[str, Any]]) -> Dict[tuple, RecommendationRecord]:
    ids = [b["finding"]["finding_id"] for b in bundles]
    if not ids:
        return {}
    rows = db.scalars(select(RecommendationRecord).where(
        RecommendationRecord.scope == scope, RecommendationRecord.finding_id.in_(ids))).all()
    return {(r.finding_id, r.evidence_hash): r for r in rows}


def _store(db: Session, scope: str, rec: Recommendation, row: Optional[RecommendationRecord],
           model: Optional[str] = None) -> RecommendationRecord:
    payload = rec.model_dump(mode="json")
    if row is None:
        row = RecommendationRecord(scope=scope, recommendation_id=rec.recommendation_id, finding_id=rec.finding_id,
                                   evidence_hash=rec.evidence_hash, rule_id=rec.rule_id)
        db.add(row)
    row.generator, row.model, row.payload, row.updated_at = rec.generator, model, payload, utcnow()
    return row


def _with_lifecycle(payload: Dict[str, Any], finding: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload["finding_status"] = (finding.get("lifecycle") or {}).get("status", "open")
    # Scores and severity always come from the current finding.
    payload["priority_score"] = (finding.get("priority") or {}).get("score", payload.get("priority_score", 0.0))
    # Commands are rebuilt from the current finding (never stored or sent to a model).
    payload["fix"] = fix_commands.fix_for(finding)
    return payload


def list_recommendations(findings: List[Dict[str, Any]], db: Optional[Session], scope: str) -> Dict[str, Any]:
    active = [f for f in findings if (f.get("lifecycle") or {}).get("status") != "false_positive"]
    bundles = build_bundles(active)
    persisted = False
    cache: Dict[tuple, RecommendationRecord] = {}
    if db is not None:
        try:
            cache = _cached(db, scope, bundles)
            persisted = True
        except SQLAlchemyError:
            db.rollback()
            db = None
    out = []
    for bundle in bundles:
        finding = bundle["finding"]
        row = cache.get((finding["finding_id"], bundle["evidence_hash"]))
        if row is not None:
            payload = row.payload
        else:
            rec = templates.build(bundle)
            payload = rec.model_dump(mode="json")
            if db is not None:
                _store(db, scope, rec, None)
        out.append(_with_lifecycle(payload, finding))
    if db is not None:
        try:
            db.commit()
            feedback = _latest_feedback(db, scope, [p["recommendation_id"] for p in out])
        except SQLAlchemyError:
            db.rollback()
            persisted, feedback = False, {}
        for payload in out:
            payload["feedback"] = feedback.get(payload["recommendation_id"])
    out.sort(key=lambda p: (-p["priority_score"], SEVERITY_ORDER.get(p["severity"], 9), p["rule_id"]))
    return {"recommendations": out, "persisted": persisted, "summary": posture_summary(out),
            "plan": fix_first_plan(out)}


def posture_summary(recs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deterministic overview; every sentence is a count of real findings."""
    by_severity = dict.fromkeys(SEVERITY_ORDER, 0)
    for rec in recs:
        by_severity[rec["severity"]] += 1
    confirmed_security = sum(1 for r in recs if r["category"] == "SECURITY" and r["evidence_state"] == "CONFIRMED")
    needs_data = sum(1 for r in recs if r["evidence_state"] == "INSUFFICIENT_EVIDENCE")
    lines = []
    if not recs:
        lines.append("No open findings from the sources that could be scanned.")
    else:
        lines.append("%d recommendation(s): %s." % (len(recs), ", ".join(
            "%d %s" % (n, k.lower()) for k, n in by_severity.items() if n)))
        if confirmed_security:
            lines.append("%d confirmed security finding(s) should be reviewed first." % confirmed_security)
        if needs_data:
            lines.append("%d finding(s) need more data before a decision can be made." % needs_data)
        top = recs[0]
        lines.append("Highest priority: %s on %s %s (score %s)." % (
            top["title"], top["resource"]["type"], top["resource"]["id"], top["priority_score"]))
    lines.append("All recommendations are advisory and require human approval; nothing is changed automatically.")
    return {"text": " ".join(lines), "by_severity": by_severity, "confirmed_security": confirmed_security,
            "insufficient_evidence": needs_data, "generator": "rules"}


def _rewrite(cfg: providers.ProviderConfig, bundle: Dict[str, Any], template: Recommendation) -> Dict[str, Any]:
    """Returns {"recommendation": Recommendation, "violations": [...], "error": str|None}."""
    try:
        raw = providers.complete(cfg, providers.prompt_payload(bundle, template.model_dump(mode="json")))
        rewrite = LLMRewrite.model_validate(raw)
    except providers.ProviderError as error:
        return {"recommendation": None, "violations": [], "error": str(error)}
    except ValidationError as error:
        return {"recommendation": None, "violations": ["response did not match the schema (%d error(s))" % error.error_count()],
                "error": None}
    violations = validator.validate(rewrite.model_dump(), bundle)
    if violations:
        return {"recommendation": None, "violations": violations, "error": None}
    merged = template.model_dump()
    merged.update({k: getattr(rewrite, k) for k in _REWRITE_FIELDS})
    if merged["correlation_note"] is None:
        merged["correlation_note"] = template.correlation_note
    merged.update(generator="llm", validation={
        "passed": True, "violations": [], "checked": "llm", "model": cfg.model,
        "cited_evidence_ids": rewrite.cited_evidence_ids})
    try:
        return {"recommendation": Recommendation.model_validate(merged), "violations": [], "error": None}
    except ValidationError as error:
        return {"recommendation": None, "violations": ["merged output failed the schema (%d error(s))" % error.error_count()],
                "error": None}


def analyze(findings: List[Dict[str, Any]], db: Session, scope: str,
            finding_ids: Optional[List[str]] = None, limit: int = 5) -> Dict[str, Any]:
    cfg = providers.config()
    active = [f for f in findings if (f.get("lifecycle") or {}).get("status") != "false_positive"]
    bundles = build_bundles(active)
    if finding_ids:
        wanted = set(finding_ids)
        targets = [b for b in bundles if b["finding"]["finding_id"] in wanted]
    else:
        targets = sorted(bundles, key=lambda b: (-(b["finding"].get("priority") or {}).get("score", 0),
                                                 SEVERITY_ORDER.get(b["finding"]["severity"], 9)))
    targets = targets[:max(1, min(limit, MAX_ANALYZE))]
    cache = _cached(db, scope, targets)
    results, calls = [], 0
    key, window_start = _today_key()
    for bundle in targets:
        finding = bundle["finding"]
        row = cache.get((finding["finding_id"], bundle["evidence_hash"]))
        template = templates.build(bundle)
        entry: Dict[str, Any] = {"finding_id": finding["finding_id"], "recommendation_id": template.recommendation_id}
        if row is not None and row.generator == "llm":
            entry.update(outcome="cached", generator="llm")
            results.append(entry)
            continue
        previous = (row.payload.get("validation") or {}) if row is not None else {}
        if previous.get("checked") == "llm" and not previous.get("provider_error"):
            # This evidence was already sent once and the answer was rejected;
            # the same input would cost another call for the same result.
            entry.update(outcome="previously_rejected", generator="rules", violations=previous.get("violations", []))
            results.append(entry)
            continue
        if cfg is None:
            _store(db, scope, template, row)
            entry.update(outcome="no_provider", generator="rules")
            results.append(entry)
            continue
        if not consume_key(db, key, daily_call_limit(), window_start):
            _store(db, scope, template, row)
            entry.update(outcome="daily_limit_reached", generator="rules")
            results.append(entry)
            continue
        calls += 1
        attempt = _rewrite(cfg, bundle, template)
        if attempt["recommendation"] is not None:
            _store(db, scope, attempt["recommendation"], row, model=cfg.model)
            entry.update(outcome="rewritten", generator="llm")
        else:
            fallback = template.model_copy(update={"validation": {
                "passed": False, "checked": "llm", "model": cfg.model, "fallback": "template",
                "violations": attempt["violations"], "provider_error": attempt["error"]}})
            _store(db, scope, fallback, row)
            entry.update(outcome="rejected" if attempt["violations"] else "provider_error", generator="rules",
                         violations=attempt["violations"], error=attempt["error"])
        results.append(entry)
    db.commit()
    return {
        "provider": cfg.public() if cfg else {"provider": "none", "model": None, "local": False, "api_key_configured": False},
        "provider_calls": calls,
        "calls_used_today": calls_used_today(db),
        "daily_call_limit": daily_call_limit(),
        "results": results,
    }


def record_feedback(db: Session, scope: str, recommendation_id: str, decision: str, note: Optional[str],
                    user_id: str) -> Optional[RecommendationFeedback]:
    row = db.scalar(select(RecommendationRecord).where(
        RecommendationRecord.scope == scope, RecommendationRecord.recommendation_id == recommendation_id))
    if row is None:
        return None
    feedback = RecommendationFeedback(scope=scope, recommendation_id=recommendation_id, finding_id=row.finding_id,
                                      user_id=user_id, decision=decision, note=note, generator=row.generator)
    db.add(feedback)
    return feedback
