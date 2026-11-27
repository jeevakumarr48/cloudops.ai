"""Fix-first plan: recommendations grouped by resource, in the order to work.

Deterministic and free: it only reorganises the recommendations that already
exist. Each group is one resource; groups are ordered by their most severe
finding, then by their highest priority score, then by how many findings a
single visit to the resource would clear. Inside a group, findings keep the
priority order, except that a correlated pair (for example "public" and
"unencrypted") is explained in ``why_first``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from services.governance_common import SEVERITY_ORDER
from services.recommendations import templates

_SKIP_STATUSES = {"accepted_risk", "false_positive", "resolved"}
MAX_GROUPS = 25


def _quick(rec: Dict[str, Any]) -> bool:
    fix = rec.get("fix") or {}
    return bool(fix.get("quick")) and rec.get("evidence_state") == "CONFIRMED"


def fix_first_plan(recommendations: List[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for rec in recommendations:
        if rec.get("finding_status", "open") in _SKIP_STATUSES or rec.get("evidence_state") == "INSUFFICIENT_EVIDENCE":
            continue
        key = (rec["resource"]["type"], rec["resource"]["id"])
        groups.setdefault(key, []).append(rec)

    out = []
    for (rtype, rid), recs in groups.items():
        recs.sort(key=lambda r: (SEVERITY_ORDER.get(r["severity"], 9), -r["priority_score"], r["rule_id"]))
        top = recs[0]
        # Only explanations whose findings are all in this group (the per-finding
        # notes can mention findings the plan leaves out, such as ones needing more data).
        rules = {r["rule_id"] for r in recs}
        notes = [text for pair, text in templates._CORRELATIONS if pair <= rules]
        out.append({
            "resource": {"type": rtype, "id": rid, "region": top["resource"].get("region")},
            "top_severity": top["severity"],
            "top_priority_score": max(r["priority_score"] for r in recs),
            "finding_count": len(recs),
            "start_with": {"recommendation_id": top["recommendation_id"], "finding_id": top["finding_id"],
                           "title": top["title"]},
            "why_first": notes[0] if notes else None,
            "steps": [{"recommendation_id": r["recommendation_id"], "finding_id": r["finding_id"],
                       "title": r["title"], "severity": r["severity"], "category": r["category"],
                       "priority_score": r["priority_score"],
                       "fix_impact": (r.get("fix") or {}).get("impact"),
                       "quick_win": _quick(r)} for r in recs],
        })
    out.sort(key=lambda g: (SEVERITY_ORDER.get(g["top_severity"], 9), -g["top_priority_score"],
                            -g["finding_count"], g["resource"]["type"], g["resource"]["id"]))
    quick_wins = sum(1 for g in out for s in g["steps"] if s["quick_win"])
    if out:
        first = out[0]
        text = "Start with %s %s: %d finding(s), the most severe is %s. %d group(s) in total; %d quick win(s) " \
               "can be fixed with a low-risk change." % (
                   first["resource"]["type"], first["resource"]["id"], first["finding_count"],
                   first["top_severity"].lower(), len(out), quick_wins)
    else:
        text = "Nothing to fix: no open findings with enough evidence to act on."
    return {"groups": out[:MAX_GROUPS], "total_groups": len(out), "quick_wins": quick_wins,
            "summary": text, "generator": "rules"}
