"""Run the recommendation evaluation.

    python -m evals.run_eval                 # offline: rules, templates, validator ($0)
    python -m evals.run_eval --live          # also ask the configured provider (Ollama is free;
                                             # a paid provider makes one call per scenario, max 10)
    python -m evals.run_eval --json out.json # machine-readable report

Metrics (offline):

- detection_accuracy        expected findings produced with the expected evidence state
- no_fabricated_findings    rules that must stay silent (healthy config or unreadable data) stay silent
- unavailable_not_assumed   unreadable checks are DATA_UNAVAILABLE, never a finding
- template_completeness     all 12 required fields present, approval always required
- template_grounding        templates pass the same validator as AI output
- savings_integrity         no savings shown unless validated from a measured figure
- correlation               multi-finding resources get the expected correlation note
- adversarial_rejection     invented or unsafe candidate rewrites rejected by the intended check
- grounded_acceptance       grounded candidate rewrites accepted (false-rejection check)

Live mode adds, per scenario: whether the provider's rewrite passed the
validator, and which checks fired. Live results are reported, not asserted,
because model output varies.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from evals import scenarios as S
from services.recommendations import providers, service, templates, validator
from services.recommendations.context import build_bundles

REQUIRED = ("title", "resource", "problem", "evidence", "why_it_matters", "suggested_action", "expected_benefits",
            "potential_risks", "estimated_savings", "confidence", "missing_information", "requires_human_approval")


def _fill(value: Any, mapping: Dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, sub in mapping.items():
            value = value.replace("{%s}" % key, sub)
        return value
    if isinstance(value, list):
        return [_fill(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, mapping) for k, v in value.items()}
    return value


class Tally:
    def __init__(self):
        self.passed = 0
        self.total = 0
        self.failures: List[str] = []

    def check(self, ok: bool, label: str) -> None:
        self.total += 1
        if ok:
            self.passed += 1
        else:
            self.failures.append(label)

    def as_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "total": self.total,
                "rate": round(self.passed / self.total, 3) if self.total else None, "failures": self.failures}


def run(live: bool = False) -> Dict[str, Any]:
    metrics = {name: Tally() for name in (
        "detection_accuracy", "no_fabricated_findings", "unavailable_not_assumed", "template_completeness",
        "template_grounding", "savings_integrity", "correlation", "adversarial_rejection", "grounded_acceptance")}
    cfg = providers.config() if live else None
    per_scenario = []
    for scenario in S.SCENARIOS:
        sid = scenario["id"]
        built = S.build(scenario)
        findings = built["findings"]
        states = {f["rule_id"]: f["evidence_state"] for f in findings}
        for rule_id, state in scenario["expect"].items():
            metrics["detection_accuracy"].check(states.get(rule_id) == state,
                                                "%s: %s expected %s, got %s" % (sid, rule_id, state, states.get(rule_id)))
        for rule_id in scenario["absent"]:
            metrics["no_fabricated_findings"].check(rule_id not in states, "%s: %s should not be reported" % (sid, rule_id))
        unavailable = {e["rule_id"] for e in built["evaluations"] if e["evidence_state"] == "DATA_UNAVAILABLE"}
        for rule_id in scenario.get("unavailable", []):
            metrics["unavailable_not_assumed"].check(rule_id in unavailable and rule_id not in states,
                                                     "%s: %s should be DATA_UNAVAILABLE" % (sid, rule_id))

        bundles = build_bundles(findings)
        recs = {}
        for bundle in bundles:
            rec = templates.build(bundle)
            dumped = rec.model_dump()
            recs[rec.rule_id] = (rec, bundle)
            label = "%s/%s" % (sid, rec.rule_id)
            metrics["template_completeness"].check(
                all(dumped.get(k) not in (None, "", []) or k == "missing_information" for k in REQUIRED)
                and dumped["requires_human_approval"] is True, label)
            violations = validator.validate(dumped, bundle, check_citations=False)
            metrics["template_grounding"].check(not violations, "%s: %s" % (label, violations))
            savings = dumped["estimated_savings"]
            measured = bundle["finding"].get("measured_savings_usd")
            metrics["savings_integrity"].check(
                (savings["validated"] is False and savings["amount_usd_per_month"] is None) if not measured
                else savings["amount_usd_per_month"] == round(float(measured), 2), label)
        if scenario.get("correlation_contains"):
            rec = recs[scenario["target"]][0]
            metrics["correlation"].check(scenario["correlation_contains"] in (rec.correlation_note or ""),
                                         "%s: correlation note missing" % sid)
        if not findings:
            metrics["template_completeness"].check(service.posture_summary([])["text"].startswith("No open findings"),
                                                   "%s: empty summary" % sid)

        candidates_out = []
        if scenario["target"]:
            rec, bundle = recs[scenario["target"]]
            mapping = {"e1": bundle["evidence"][0]["id"], "res": bundle["resource"]["id"]}
            cost = S.cost_candidates(bundle["finding"]) if scenario["id"] == "cost_weekly_increase" else {}
            for candidate in scenario["candidates"]:
                rewrite = candidate["rewrite"]
                rewrite = _fill(cost.get(rewrite, rewrite) if isinstance(rewrite, str) else rewrite, mapping)
                violations = validator.validate(rewrite, bundle)
                label = "%s: %s" % (sid, candidate["label"])
                if candidate["expect"] == "accept":
                    metrics["grounded_acceptance"].check(not violations, "%s -> %s" % (label, violations))
                else:
                    metrics["adversarial_rejection"].check(any(candidate["check"] in v for v in violations),
                                                           "%s -> expected '%s', got %s" % (label, candidate["check"], violations))
                candidates_out.append({"label": candidate["label"], "expect": candidate["expect"],
                                       "violations": violations})
        entry: Dict[str, Any] = {"id": sid, "description": scenario["description"],
                                 "findings": sorted(states.items()), "candidates": candidates_out}
        if live and scenario["target"]:
            rec, bundle = recs[scenario["target"]]
            if cfg is None:
                entry["live"] = {"skipped": "no provider configured"}
            else:
                attempt = service._rewrite(cfg, bundle, rec)
                entry["live"] = {"model": cfg.model, "accepted": attempt["recommendation"] is not None,
                                 "violations": attempt["violations"], "error": attempt["error"]}
        per_scenario.append(entry)

    summary = {name: tally.as_dict() for name, tally in metrics.items()}
    report: Dict[str, Any] = {"scenarios": len(S.SCENARIOS), "metrics": summary, "results": per_scenario,
                              "all_passed": all(t.passed == t.total for t in metrics.values())}
    if live:
        live_rows = [r["live"] for r in per_scenario if "live" in r and "accepted" in r["live"]]
        report["live"] = {"provider": cfg.public() if cfg else None, "attempted": len(live_rows),
                          "accepted": sum(1 for r in live_rows if r["accepted"])}
    return report


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="also call the configured AI provider")
    parser.add_argument("--json", metavar="PATH", help="write the full report as JSON")
    args = parser.parse_args(argv)
    report = run(live=args.live)
    for name, tally in report["metrics"].items():
        rate = "n/a" if tally["rate"] is None else "%.0f%%" % (100 * tally["rate"])
        print("%-26s %3d/%-3d %s" % (name, tally["passed"], tally["total"], rate))
        for failure in tally["failures"]:
            print("    FAIL", failure)
    if "live" in report:
        print("live provider: %s" % json.dumps(report["live"]))
        for row in report["results"]:
            if "live" in row:
                print("    %-34s %s" % (row["id"], json.dumps(row["live"])))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, default=str)
    print("ALL PASSED" if report["all_passed"] else "FAILURES")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
