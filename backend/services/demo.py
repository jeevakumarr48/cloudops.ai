"""Public demo data: the evaluation scenarios run through the real rules.

The demo lets anyone explore the console without an account or an AWS
connection. Every record comes from the synthetic discovery inputs in
``evals.scenarios`` (the same ones the offline evaluation uses), passed through
the real rule, scoring, recommendation and fix-command code. Nothing here reads
AWS, writes to the database or calls an AI provider, and every response is
labelled as sample data.

Set ``CLOUDOPS_DEMO_ENABLED=false`` to turn the demo endpoints off.
"""

from __future__ import annotations

import copy
import os
import threading
from typing import Any, Dict, List

from evals import scenarios
from services import governance_engine
from services.governance_common import FINDING_STATES

SCOPE = "demo"
LABEL = ("Sample data for demonstration. These resources do not exist; they are synthetic inputs run "
         "through the real CloudOps rules.")
# Fixed so the demo reads the same on every visit and in screenshots.
SCANNED_AT = "2026-11-25T09:00:00+00:00"

_lock = threading.Lock()
_cache: Dict[str, Any] = {}


def enabled() -> bool:
    return os.environ.get("CLOUDOPS_DEMO_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def _build() -> Dict[str, Any]:
    by_source: Dict[str, List[Dict[str, Any]]] = {name: [] for name in governance_engine.SOURCES}
    for scenario in scenarios.SCENARIOS:
        source = scenario["id"].split("_")[0]
        if source not in by_source:  # Terraform scenarios are plan inputs, not account resources
            continue
        by_source[source].extend(scenario["build"]())
    evaluations: List[Dict[str, Any]] = []
    for source, items in by_source.items():
        for evaluation in items:
            evaluation["source"] = source
            if evaluation["evidence_state"] in FINDING_STATES:
                evaluation["priority"] = governance_engine.score(evaluation)
                evaluation["lifecycle"] = {
                    "status": "open", "first_detected": SCANNED_AT, "last_detected": SCANNED_AT,
                    "resolved_at": None, "times_reopened": 0, "status_note": None, "persisted": False,
                }
            evaluations.append(evaluation)
    sources = {name: {"status": "ok", "error": None, "evaluated_rules": len(items)}
               for name, items in by_source.items()}
    findings = [e for e in evaluations if e["evidence_state"] in FINDING_STATES]
    findings.sort(key=governance_engine.sort_key)
    return {"scanned_at": SCANNED_AT, "sources": sources, "evaluations": evaluations, "findings": findings}


def scan() -> Dict[str, Any]:
    """The demo scan, built once per process and copied for each caller."""
    with _lock:
        if "scan" not in _cache:
            _cache["scan"] = _build()
        return copy.deepcopy(_cache["scan"])
