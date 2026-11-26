"""Phase 7: the offline recommendation evaluation must pass in full."""

import re

from evals import run_eval, scenarios
from services.recommendations import providers, templates, validator


def test_ten_scenarios_cover_every_source():
    assert len(scenarios.SCENARIOS) == 10
    assert len({s["id"] for s in scenarios.SCENARIOS}) == 10
    targets = {s["target"].split("_")[0] for s in scenarios.SCENARIOS if s["target"]}
    assert targets == {"S3", "RDS", "EC2", "COST", "IAC"}
    assert any(not s["expect"] for s in scenarios.SCENARIOS)       # a healthy, no-findings case
    assert any(s.get("unavailable") for s in scenarios.SCENARIOS)  # a permissions-denied case


def test_offline_eval_passes_every_metric():
    report = run_eval.run()
    failures = {k: v["failures"] for k, v in report["metrics"].items() if v["failures"]}
    assert report["all_passed"], failures
    assert report["metrics"]["adversarial_rejection"]["total"] >= 20
    assert report["metrics"]["grounded_acceptance"]["total"] >= 9


def test_eval_detects_a_weakened_validator(monkeypatch):
    monkeypatch.setattr(validator, "_UNAPPROVED_RE", re.compile(r"(?!x)x"))
    report = run_eval.run()
    assert not report["all_passed"]
    assert report["metrics"]["adversarial_rejection"]["failures"]


def test_eval_detects_an_invented_figure_in_a_template(monkeypatch):
    text = dict(templates.RULE_TEXT["S3_PUBLIC_POLICY"], why="This bucket costs $5 a month to serve.")
    monkeypatch.setitem(templates.RULE_TEXT, "S3_PUBLIC_POLICY", text)
    assert run_eval.run()["metrics"]["template_grounding"]["failures"]


def test_live_mode_without_provider_makes_no_calls(monkeypatch):
    for key in ("CLOUDOPS_AI_PROVIDER", "CLOUDOPS_AI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(providers, "complete", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    report = run_eval.run(live=True)
    assert report["live"]["attempted"] == 0
    assert all(r["live"] == {"skipped": "no provider configured"} for r in report["results"] if "live" in r)


def test_live_mode_reports_provider_results(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_AI_PROVIDER", "ollama")
    calls = []

    def complete(cfg, payload, timeout=25.0):
        calls.append(payload["resource"]["id"])
        draft = payload["draft"]
        return dict({k: draft[k] for k in ("problem", "why_it_matters", "suggested_action", "expected_benefits",
                                           "potential_risks", "correlation_note")},
                    cited_evidence_ids=[payload["evidence"][0]["evidence_id"]])

    monkeypatch.setattr(providers, "complete", complete)
    report = run_eval.run(live=True)
    assert len(calls) == 9  # one per scenario with a target
    assert report["live"]["attempted"] == 9 and report["live"]["accepted"] == 9


def test_cli_exit_code(tmp_path, capsys):
    out = tmp_path / "report.json"
    assert run_eval.main(["--json", str(out)]) == 0
    assert out.exists() and "ALL PASSED" in capsys.readouterr().out
