"""Copy-ready fix commands and the fix-first plan (both deterministic, never executed)."""

import re
import shlex

import pytest
from fastapi.testclient import TestClient

import main
from services import governance_engine
from services.governance_common import CONFIRMED, INSUFFICIENT_EVIDENCE, NO_ISSUE, POTENTIAL, Evaluation
from services.recommendations import fix_commands, providers, service
from services.recommendations.plan import fix_first_plan

PASSWORD = "correct horse battery"
RTYPE = {"S3": "bucket-a", "RDS": "orders-db", "EC2": "i-0123456789abcdef0", "COST": "aws-account"}


def make(rule_id, state=CONFIRMED, severity="HIGH", resource=None, region="us-east-1", observations=None,
         status="open"):
    prefix = rule_id.split("_")[0]
    rtype = {"COST": "ACCOUNT"}.get(prefix, prefix)
    resource = resource or RTYPE[prefix]
    ev = Evaluation(rtype, resource, region, rule_id, "SECURITY", "Title for %s" % rule_id, "test")
    for observation in observations or ["Observed condition for %s." % rule_id]:
        ev.cite("test:Describe", observation)
    result = ev.result(state, severity, "Description of %s on %s." % (rule_id, resource),
                       recommendation="Fix it after review.", confidence="high")
    result["priority"] = governance_engine.score(result) if rule_id in governance_engine.RULE_META else {"score": 1.0}
    result["lifecycle"] = {"status": status}
    return result


@pytest.mark.parametrize("rule_id", fix_commands.supported_rules())
def test_every_supported_rule_builds_a_reviewable_plan(rule_id):
    fix = fix_commands.fix_for(make(rule_id))
    assert fix["runs_automatically"] is False and "never runs" in fix["notice"]
    assert fix["impact"] in ("read_only", "safe", "disruptive", "destructive")
    assert fix["steps"] and all(s["command"].strip() for s in fix["steps"])
    for step in fix["before"] + fix["steps"]:
        assert step["impact"] in ("read_only", "safe", "disruptive", "destructive")
        if not step["command"].startswith("cat >"):
            assert step["command"].startswith("aws ")
    # Every placeholder a person must fill is listed.
    text = " ".join(s["command"] for s in fix["before"] + fix["steps"])
    assert set(re.findall(r"<[A-Z][A-Z0-9_]*>", text)) <= set(fix["placeholders"])


def test_rules_with_resources_are_all_covered():
    expected = {r for r in governance_engine.RULE_META if not r.startswith("IAC_")}
    assert expected <= set(fix_commands.supported_rules())


def test_resource_id_and_region_are_filled_in():
    fix = fix_commands.fix_for(make("S3_DEFAULT_ENCRYPTION", resource="logs-prod", region="eu-west-2"))
    assert "--bucket logs-prod --region eu-west-2" in fix["steps"][0]["command"]
    assert fix["impact"] == "safe" and fix["undo"]


def test_no_region_flag_for_global_or_odd_values():
    assert "--region" not in fix_commands.fix_for(make("S3_VERSIONING", region="global"))["steps"][0]["command"]
    assert "--region" not in fix_commands.fix_for(make("S3_VERSIONING", region="us-east-1; rm -rf /"))["steps"][0]["command"]


def test_odd_resource_ids_are_shell_quoted():
    nasty = "bucket$(touch pwned)"
    command = fix_commands.fix_for(make("S3_VERSIONING", resource=nasty))["steps"][0]["command"]
    assert shlex.quote(nasty) in command
    assert shlex.split(command)[shlex.split(command).index("--bucket") + 1] == nasty


def test_judgement_values_are_placeholders_not_guesses():
    assert fix_commands.fix_for(make("EC2_LOW_UTILIZATION"))["placeholders"] == ["<SMALLER_INSTANCE_TYPE>"]
    assert fix_commands.fix_for(make("RDS_BACKUP_RETENTION"))["placeholders"] == ["<RETENTION_DAYS>"]
    assert "<OWNER>" in fix_commands.fix_for(make("EC2_MISSING_OWNER_TAG"))["placeholders"]


def test_security_group_ids_come_from_evidence():
    finding = make("EC2_OPEN_ADMIN_PORTS", observations=[
        "Instance has a public IPv4 address.",
        "sg-0abc1234 allows SSH (port 22) from the internet.",
        "sg-0abc1234 allows RDP (port 3389) from the internet.",
    ])
    fix = fix_commands.fix_for(finding)
    revokes = [s["command"] for s in fix["steps"] if "revoke" in s["command"]]
    assert len(revokes) == 4 and all("sg-0abc1234" in c for c in revokes)
    assert any("--port 3389" in c for c in revokes)
    assert "<SECURITY_GROUP_ID>" not in fix["placeholders"]


def test_unparseable_security_group_falls_back_to_placeholder():
    fix = fix_commands.fix_for(make("EC2_OPEN_ADMIN_PORTS", observations=["Something else."]))
    assert "<SECURITY_GROUP_ID>" in fix["placeholders"]


def test_destructive_steps_are_labelled_and_have_no_undo():
    fix = fix_commands.fix_for(make("EC2_STOPPED_INSTANCE"))
    assert fix["impact"] == "destructive" and fix["undo"] is None
    order = [s["impact"] for s in fix["steps"]]
    assert order.index("safe") < order.index("destructive")  # backup image before terminate


def test_quick_wins_are_single_low_risk_commands():
    assert fix_commands.fix_for(make("S3_DEFAULT_ENCRYPTION"))["quick"] is True
    assert fix_commands.fix_for(make("EC2_MISSING_OWNER_TAG"))["quick"] is True
    assert fix_commands.fix_for(make("RDS_STORAGE_ENCRYPTION"))["quick"] is False  # a migration, not a quick fix
    assert fix_commands.fix_for(make("RDS_PUBLIC_ACCESS"))["quick"] is False


def test_plan_omits_the_generic_related_findings_note():
    recs = _recs(make("EC2_MISSING_OWNER_TAG", resource="i-1"), make("EC2_STOPPED_INSTANCE", resource="i-1"))
    assert fix_first_plan(recs)["groups"][0]["why_first"] is None
    # A pair is only explained when both findings are in the plan.
    recs = _recs(make("EC2_MISSING_ENVIRONMENT_TAG", resource="i-2"),
                 make("EC2_LOW_UTILIZATION", resource="i-2", state=INSUFFICIENT_EVIDENCE))
    assert fix_first_plan(recs)["groups"][0]["why_first"] is None


def test_encryption_migration_never_deletes_the_original():
    fix = fix_commands.fix_for(make("RDS_STORAGE_ENCRYPTION"))
    text = " ".join(s["command"] for s in fix["steps"])
    assert "delete-db-instance" not in text and "restore-db-instance-from-db-snapshot" in text


def test_no_commands_without_enough_evidence_or_for_terraform():
    assert fix_commands.fix_for(make("S3_VERSIONING", state=INSUFFICIENT_EVIDENCE)) is None
    assert fix_commands.fix_for(make("S3_VERSIONING", state=NO_ISSUE)) is None
    assert fix_commands.fix_for({"rule_id": "IAC_COST_INCREASE", "evidence_state": CONFIRMED}) is None
    assert fix_commands.fix_for(make("S3_VERSIONING", state=POTENTIAL)) is not None


def test_commands_never_reach_the_model():
    finding = make("S3_VERSIONING")
    rec = service.list_recommendations([finding], None, "global")["recommendations"][0]
    assert rec["fix"]["steps"]
    bundle = service.build_bundles([finding])[0]
    payload = providers.prompt_payload(bundle, rec)
    assert "aws s3api" not in str(payload)


# --- plan ------------------------------------------------------------------------


def _recs(*findings):
    return service.list_recommendations(list(findings), None, "global")["recommendations"]


def test_plan_groups_by_resource_and_orders_by_severity():
    recs = _recs(
        make("S3_VERSIONING", severity="LOW", resource="quiet-bucket"),
        make("S3_PUBLIC_POLICY", severity="CRITICAL", resource="open-bucket"),
        make("S3_DEFAULT_ENCRYPTION", severity="HIGH", resource="open-bucket"),
    )
    plan = fix_first_plan(recs)
    assert [g["resource"]["id"] for g in plan["groups"]] == ["open-bucket", "quiet-bucket"]
    first = plan["groups"][0]
    assert first["finding_count"] == 2 and first["top_severity"] == "CRITICAL"
    assert first["start_with"]["title"] == "Title for S3_PUBLIC_POLICY"
    assert first["why_first"] and "unencrypted" in first["why_first"]
    assert plan["summary"].startswith("Start with S3 open-bucket: 2 finding(s)")
    assert plan["generator"] == "rules"


def test_plan_marks_quick_wins_and_skips_closed_or_unclear_findings():
    recs = _recs(
        make("S3_DEFAULT_ENCRYPTION", resource="a"),
        make("S3_PUBLIC_POLICY", resource="b", status="accepted_risk"),
        make("S3_LIFECYCLE", resource="c", state=INSUFFICIENT_EVIDENCE),
    )
    plan = fix_first_plan(recs)
    assert [g["resource"]["id"] for g in plan["groups"]] == ["a"]
    assert plan["groups"][0]["steps"][0]["quick_win"] is True and plan["quick_wins"] == 1


def test_empty_plan():
    plan = fix_first_plan([])
    assert plan["groups"] == [] and plan["summary"].startswith("Nothing to fix")


def test_endpoint_returns_fix_and_plan(monkeypatch):
    monkeypatch.setattr(governance_engine, "_s3_source", lambda refresh: [make("S3_PUBLIC_POLICY")])
    for name in ("_ec2_source", "_rds_source", "_cost_source"):
        monkeypatch.setattr(governance_engine, name, lambda refresh: [])
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDOPS_OPERATOR_EMAILS", "ops@example.com")
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"email": "ops@example.com", "password": PASSWORD})
    body = client.get("/api/ai/recommendations").json()
    assert body["recommendations"][0]["fix"]["runs_automatically"] is False
    assert body["plan"]["groups"][0]["resource"]["id"] == "bucket-a"
    # Cached records keep getting fresh commands on the second read.
    assert client.get("/api/ai/recommendations").json()["recommendations"][0]["fix"]["steps"]
