"""Shared building blocks for deterministic governance rules.

Every rule evaluation has exactly one evidence state:

- ``CONFIRMED``             AWS data directly shows the condition
- ``POTENTIAL``             the condition may matter; human context needed
- ``INSUFFICIENT_EVIDENCE`` data was read but is not enough to decide
- ``NO_ISSUE``              the check passed
- ``DATA_UNAVAILABLE``      the data could not be read (permissions/errors)

Only CONFIRMED, POTENTIAL and INSUFFICIENT_EVIDENCE are reported as findings.
Severity is only meaningful for findings; other states carry ``INFO``.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

CONFIRMED = "CONFIRMED"
POTENTIAL = "POTENTIAL"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
NO_ISSUE = "NO_ISSUE"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
EVIDENCE_STATES = (CONFIRMED, POTENTIAL, INSUFFICIENT_EVIDENCE, NO_ISSUE, DATA_UNAVAILABLE)
FINDING_STATES = (CONFIRMED, POTENTIAL, INSUFFICIENT_EVIDENCE)
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
PRODUCTION_TAG_VALUES = {"production", "prod", "prd"}


def finding_id(resource_type: str, rule_id: str, resource_id: str) -> str:
    raw = "%s|%s|%s" % (resource_type.lower(), rule_id, resource_id)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def environment(tags: Dict[str, Any]) -> Optional[str]:
    """Return the lower-cased environment tag value, or None if untagged."""
    for key in ("Environment", "environment", "Env", "env", "Stage", "stage"):
        value = tags.get(key)
        if value:
            return str(value).strip().lower()
    return None


def is_production(tags: Dict[str, Any]) -> Optional[bool]:
    env = environment(tags)
    if env is None:
        return None
    return env in PRODUCTION_TAG_VALUES


class Evaluation:
    """Accumulates cited evidence for one rule on one resource."""

    def __init__(self, resource_type: str, resource_id: str, region: Optional[str],
                 rule_id: str, category: str, title: str, detection_source: str):
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.region = region
        self.rule_id = rule_id
        self.category = category
        self.title = title
        self.detection_source = detection_source
        self.evidence: List[Dict[str, str]] = []

    def cite(self, source: str, observation: str) -> "Evaluation":
        self.evidence.append({
            "id": "%s-e%d" % (self.rule_id.lower(), len(self.evidence) + 1),
            "source": source,
            "observation": observation,
        })
        return self

    def result(
        self,
        state: str,
        severity: str = "INFO",
        description: str = "",
        recommendation: Optional[str] = None,
        remediation_steps: Optional[List[str]] = None,
        confidence: str = "high",
        missing_information: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if state not in EVIDENCE_STATES:
            raise ValueError("Unknown evidence state: %s" % state)
        return {
            "finding_id": finding_id(self.resource_type, self.rule_id, self.resource_id),
            "rule_id": self.rule_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "region": self.region,
            "category": self.category,
            "severity": severity if state in FINDING_STATES else "INFO",
            "evidence_state": state,
            "title": self.title,
            "description": description,
            "evidence": self.evidence,
            "detection_source": self.detection_source,
            "recommendation": recommendation,
            "remediation_steps": remediation_steps or [],
            "potential_monthly_impact": None,
            "confidence": confidence,
            "missing_information": missing_information or [],
            "requires_human_approval": True,
        }

    def unavailable(self, what: str, status: Optional[str], iam_action: str) -> Dict[str, Any]:
        reason = "permission denied" if status == "access_denied" else "the request failed"
        self.cite(iam_action, "Could not read %s: %s." % (what, reason))
        return self.result(
            DATA_UNAVAILABLE,
            description="This check could not run, so the setting is unknown (not assumed safe or unsafe).",
            missing_information=["Grant %s to the CloudOps AI read-only role." % iam_action],
        )


def summarize(evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
    findings = sorted(
        (e for e in evaluations if e["evidence_state"] in FINDING_STATES),
        key=lambda e: (SEVERITY_ORDER.get(e["severity"], 9), e["rule_id"], e["resource_id"]),
    )
    by_severity = dict.fromkeys(SEVERITY_ORDER, 0)
    by_state = dict.fromkeys(EVIDENCE_STATES, 0)
    for evaluation in evaluations:
        by_state[evaluation["evidence_state"]] += 1
    for finding in findings:
        by_severity[finding["severity"]] += 1
    return {"findings": findings, "by_severity": by_severity, "by_state": by_state}
