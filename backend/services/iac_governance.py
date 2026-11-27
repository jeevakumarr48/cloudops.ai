"""Adapter from the original Terraform/Infracost findings to the unified format.

The original ``decision_engine.analyze_iac_changes`` stays the single source
of IaC detection logic; this only maps its output, attaches the Infracost
cost change as a measured figure and assigns stable rule ids.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.governance_common import CONFIRMED, POTENTIAL, finding_id

__all__ = ["to_unified"]

_RULES = {
    "Significant estimated monthly infrastructure cost": ("IAC_HIGH_MONTHLY_COST", "COST", "MEDIUM", POTENTIAL),
    "Estimated monthly infrastructure cost increase": ("IAC_COST_INCREASE", "COST", "MEDIUM", CONFIRMED),
    "Invalid or missing governance tags": ("IAC_TAGGING_POLICY", "GOVERNANCE", "MEDIUM", CONFIRMED),
    "Infrastructure policy violation": ("IAC_POLICY_VIOLATION", "INFRASTRUCTURE", "MEDIUM", CONFIRMED),
    "Potential high-cost underutilized resource": ("IAC_HIGH_COST_LOW_CPU", "UTILIZATION", "HIGH", POTENTIAL),
    "Potential overprovisioning in infrastructure change": ("IAC_OVERPROVISIONED_CHANGE", "INFRASTRUCTURE", None, POTENTIAL),
}


def to_unified(legacy: List[Dict[str, Any]], infracost: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    change = None
    if isinstance(infracost, dict) and infracost.get("status") == "ok":
        try:
            change = float(infracost.get("monthly_cost_change"))
        except (TypeError, ValueError):
            change = None
    unified = []
    for index, item in enumerate(legacy):
        rule_id, category, severity, state = _RULES.get(
            item.get("issue"), ("IAC_OTHER", "INFRASTRUCTURE", None, POTENTIAL)
        )
        severity = severity or (item.get("severity") or "medium").upper()
        resource_id = str(item.get("resource_id") or "terraform")
        evidence = [
            {"id": "%s-e%d" % (rule_id.lower(), n + 1), "source": "terraform/infracost", "observation": text}
            for n, text in enumerate(item.get("evidence") or [])
        ]
        record = {
            "finding_id": finding_id("terraform", rule_id, "%s#%d" % (resource_id, index)),
            "rule_id": rule_id,
            "resource_type": item.get("resource_type") or "terraform",
            "resource_id": resource_id,
            "region": None,
            "category": category,
            "severity": severity,
            "evidence_state": state,
            "title": item.get("issue"),
            "description": item.get("recommendation"),
            "evidence": evidence,
            "detection_source": "terraform",
            "recommendation": item.get("recommendation"),
            "remediation_steps": ["Review the plan with its author before approving it.",
                                  "Re-run the analysis after changing the plan."],
            "potential_monthly_impact": None,
            "confidence": "high" if state == CONFIRMED else "medium",
            "missing_information": [],
            "requires_human_approval": True,
        }
        if rule_id in ("IAC_COST_INCREASE",) and change is not None:
            record["measured_usd"] = round(change, 2)
        unified.append(record)
    return unified
