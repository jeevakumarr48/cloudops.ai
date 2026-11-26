"""Context builder: one evidence bundle per finding, with resource context.

The bundle is the only thing a generator (template or LLM) sees. It holds
the finding, the other findings on the same resource (for correlation) and
the set of facts the output is allowed to mention.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def evidence_hash(finding: Dict[str, Any]) -> str:
    """Changes only when the evidence behind a finding changes."""
    material = {
        "rule": finding["rule_id"],
        "resource": finding["resource_id"],
        "state": finding["evidence_state"],
        "severity": finding["severity"],
        "evidence": [e["observation"] for e in finding.get("evidence", [])],
        "missing": finding.get("missing_information", []),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def build_bundles(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_resource: Dict[tuple, List[Dict[str, Any]]] = {}
    for finding in findings:
        by_resource.setdefault((finding["resource_type"], str(finding["resource_id"])), []).append(finding)

    bundles = []
    for finding in findings:
        key = (finding["resource_type"], str(finding["resource_id"]))
        related = [f for f in by_resource[key] if f["finding_id"] != finding["finding_id"]]
        evidence = [dict(e) for e in finding.get("evidence", [])]
        related_evidence = [
            dict(e, evidence_id="%s:%s" % (f["finding_id"], e["id"]))
            for f in related for e in f.get("evidence", [])
        ]
        texts = [e["observation"] for e in evidence + related_evidence]
        texts += [finding.get("description") or "", finding.get("title") or ""]
        bundles.append({
            "finding": finding,
            "resource": {"type": finding["resource_type"], "id": str(finding["resource_id"]),
                         "region": finding.get("region")},
            "evidence": evidence,
            "related": [{"finding_id": f["finding_id"], "rule_id": f["rule_id"], "title": f["title"],
                         "severity": f["severity"], "category": f["category"],
                         "evidence_state": f["evidence_state"]} for f in related],
            "related_evidence": related_evidence,
            "allowed_numbers": sorted({n for text in texts for n in _NUMBER_RE.findall(text)}),
            "allowed_text": " ".join(texts),
            "has_security_finding": any(
                f["category"] == "SECURITY" and f["evidence_state"] in ("CONFIRMED", "POTENTIAL")
                for f in [finding] + related
            ),
            "evidence_hash": evidence_hash(finding),
        })
    return bundles
