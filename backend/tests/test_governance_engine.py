"""Unified governance engine: rules, scoring, lifecycle and endpoints."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import main
from services import cost_governance, cost_service, ec2_governance, governance_engine
from services.governance_common import (
    CONFIRMED,
    DATA_UNAVAILABLE,
    INSUFFICIENT_EVIDENCE,
    NO_ISSUE,
    POTENTIAL,
    Evaluation,
)

PASSWORD = "correct horse battery"


def finding(rule_id="S3_PUBLIC_POLICY", state=CONFIRMED, severity="CRITICAL", resource="bucket-a",
            rtype="S3", category="SECURITY", **extra):
    ev = Evaluation(rtype, resource, "us-east-1", rule_id, category, "title", "test")
    ev.cite("test", "observation")
    result = ev.result(state, severity, "description")
    result.update(extra)
    return result


# --- scoring -------------------------------------------------------------------


def test_score_confirmed_public_bucket():
    result = governance_engine.score(finding())
    # (0.45*100 + 0.30*100 + 0) * 1.0 - effort(low)=0 - risk(medium)=5
    assert result["score"] == 70.0
    assert result["inputs"]["exposure"] == 100


def test_score_uses_only_measured_dollars():
    without = governance_engine.score(finding("COST_WEEKLY_INCREASE", CONFIRMED, "MEDIUM", "aws-account", "ACCOUNT", "COST"))
    with_usd = governance_engine.score(finding("COST_WEEKLY_INCREASE", CONFIRMED, "MEDIUM", "aws-account", "ACCOUNT", "COST", measured_usd=15.0))
    assert without["inputs"]["financial"] == 0
    assert with_usd["inputs"]["financial"] == 80.0  # 20*log2(16)
    assert with_usd["score"] > without["score"]


def test_potential_and_insufficient_evidence_rank_lower():
    confirmed = governance_engine.score(finding("S3_DEFAULT_ENCRYPTION", CONFIRMED, "MEDIUM"))["score"]
    potential = governance_engine.score(finding("S3_DEFAULT_ENCRYPTION", POTENTIAL, "MEDIUM"))["score"]
    insufficient = governance_engine.score(finding("S3_DEFAULT_ENCRYPTION", INSUFFICIENT_EVIDENCE, "MEDIUM"))["score"]
    assert confirmed > potential > insufficient


def test_production_resize_gets_high_risk_penalty():
    prod = finding("EC2_LOW_UTILIZATION", POTENTIAL, "LOW", "i-1", "EC2", "UTILIZATION")
    prod["description"] = "this is a production instance"
    assert governance_engine.score(prod)["inputs"]["risk"] == "high"


# --- EC2 rules -----------------------------------------------------------------


def instance(**overrides):
    base = {"InstanceId": "i-1", "InstanceType": "t3.large", "State": {"Name": "running"},
            "Placement": {"AvailabilityZone": "us-east-1a"},
            "Tags": [{"Key": "Owner", "Value": "jeeva"}, {"Key": "Environment", "Value": "development"}],
            "SecurityGroups": [{"GroupId": "sg-1"}]}
    base.update(overrides)
    return base


class FakeEC2:
    def __init__(self, permissions):
        self.permissions = permissions

    def describe_security_groups(self, GroupIds):
        return {"SecurityGroups": [{"GroupId": "sg-1", "IpPermissions": self.permissions}]}


def by_rule(evaluations):
    return {e["rule_id"]: e for e in evaluations}


def test_open_ssh_on_public_instance_is_confirmed_high():
    inst = instance(PublicIpAddress="203.0.113.5")
    exposure = ec2_governance.admin_port_exposure(FakeEC2([
        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]), [inst])
    rule = by_rule(ec2_governance.evaluate_instance(inst, None, "ok", exposure["i-1"]))["EC2_OPEN_ADMIN_PORTS"]
    assert (rule["evidence_state"], rule["severity"]) == (CONFIRMED, "HIGH")


def test_private_instance_has_no_exposure():
    rule = by_rule(ec2_governance.evaluate_instance(instance(), None, "ok", None))["EC2_OPEN_ADMIN_PORTS"]
    assert rule["evidence_state"] == NO_ISSUE


def test_ec2_utilization_needs_14_days_coverage():
    thin = {"cpu_average": 2.0, "cpu_max": 5.0, "data_points": 10}
    full = {"cpu_average": 2.0, "cpu_max": 5.0, "data_points": 24}
    assert by_rule(ec2_governance.evaluate_instance(instance(), thin, "ok", None))["EC2_LOW_UTILIZATION"]["evidence_state"] == INSUFFICIENT_EVIDENCE
    low = by_rule(ec2_governance.evaluate_instance(instance(), full, "ok", None))["EC2_LOW_UTILIZATION"]
    assert (low["evidence_state"], low["severity"], low["confidence"]) == (POTENTIAL, "MEDIUM", "medium")
    prod = instance(Tags=[{"Key": "Environment", "Value": "production"}])
    prod_rule = by_rule(ec2_governance.evaluate_instance(prod, full, "ok", None))["EC2_LOW_UTILIZATION"]
    assert (prod_rule["severity"], prod_rule["confidence"]) == ("LOW", "low")


def test_ec2_metrics_failure_is_data_unavailable():
    rule = by_rule(ec2_governance.evaluate_instance(instance(), None, "error", None))["EC2_LOW_UTILIZATION"]
    assert rule["evidence_state"] == DATA_UNAVAILABLE


def test_missing_tags_are_flagged():
    rules = by_rule(ec2_governance.evaluate_instance(instance(Tags=[]), None, "ok", None))
    assert rules["EC2_MISSING_OWNER_TAG"]["evidence_state"] == CONFIRMED
    assert rules["EC2_MISSING_ENVIRONMENT_TAG"]["evidence_state"] == CONFIRMED


# --- cost rules ----------------------------------------------------------------


def daily_series(previous, recent):
    start = date(2026, 11, 1)
    values = [previous] * 7 + [recent] * 7 + [0.1]  # last entry = today (partial)
    return [{"date": (start + timedelta(days=i)).isoformat(), "total": v,
             "services": {"Amazon EC2": v}} for i, v in enumerate(values)]


def test_weekly_cost_increase_is_confirmed_with_drivers():
    result = cost_governance.evaluate_costs({"daily": daily_series(1.0, 2.0)})[0]
    assert (result["evidence_state"], result["severity"]) == (CONFIRMED, "HIGH")
    assert result["measured_usd"] == 7.0
    assert any("Amazon EC2" in e["observation"] for e in result["evidence"])


def test_flat_or_tiny_spend_is_no_issue():
    assert cost_governance.evaluate_costs({"daily": daily_series(1.0, 1.05)})[0]["evidence_state"] == NO_ISSUE
    assert cost_governance.evaluate_costs({"daily": daily_series(0.01, 0.1)})[0]["evidence_state"] == NO_ISSUE


def test_short_or_missing_series_is_insufficient():
    assert cost_governance.evaluate_costs({"daily": daily_series(1, 2)[:5]})[0]["evidence_state"] == INSUFFICIENT_EVIDENCE
    assert cost_governance.evaluate_costs({"services": []})[0]["evidence_state"] == INSUFFICIENT_EVIDENCE


def test_daily_cost_summary_includes_per_day_series(monkeypatch):
    cost_service._cache.clear()

    class CE:
        def get_cost_and_usage(self, **kwargs):
            return {"ResultsByTime": [
                {"TimePeriod": {"Start": "2026-11-01"}, "Groups": [
                    {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "0.5", "Unit": "USD"}}}]},
                {"TimePeriod": {"Start": "2026-11-02"}, "Groups": [
                    {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "0.25", "Unit": "USD"}}}]},
            ]}

    monkeypatch.setattr(cost_service, "create_cost_explorer_client", lambda region: CE())
    summary = cost_service.get_cost_summary(period="daily")
    assert summary["daily"] == [
        {"date": "2026-11-01", "total": 0.5, "services": {"Amazon S3": 0.5}},
        {"date": "2026-11-02", "total": 0.25, "services": {"Amazon S3": 0.25}},
    ]
    cost_service._cache.clear()


# --- engine lifecycle ------------------------------------------------------------


@pytest.fixture
def sources(monkeypatch):
    state = {"s3": [finding()], "ec2": [], "fail": set()}

    def runner(name):
        def run(refresh):
            if name in state["fail"]:
                raise {"s3": governance_engine.S3AccessError, "ec2": governance_engine.AWSAccessError}[name]("down")
            return [dict(f) for f in state[name]]
        return run

    monkeypatch.setattr(governance_engine, "_s3_source", runner("s3"))
    monkeypatch.setattr(governance_engine, "_ec2_source", runner("ec2"))
    monkeypatch.setattr(governance_engine, "_rds_source", lambda refresh: [])
    monkeypatch.setattr(governance_engine, "_cost_source", lambda refresh: [])
    return state


def scan():
    return governance_engine.sync(governance_engine.collect())


def test_lifecycle_open_resolve_reopen(sources):
    first = scan()[0]["lifecycle"]
    assert first["status"] == "open" and first["persisted"] is True
    sources["s3"] = []
    assert scan() == []
    resolved = governance_engine.resolved_findings()
    assert resolved[0]["lifecycle"]["status"] == "resolved"
    sources["s3"] = [finding()]
    again = scan()[0]["lifecycle"]
    assert again["status"] == "open" and again["times_reopened"] == 1
    assert again["first_detected"] == first["first_detected"]


def test_failed_source_never_resolves_its_findings(sources):
    scan()
    sources["fail"].add("s3")
    result = governance_engine.collect()
    assert result["sources"]["s3"] == {"status": "unavailable", "error": "down", "evaluated_rules": 0}
    governance_engine.sync(result)
    assert governance_engine.resolved_findings() == []


def test_scan_is_reused_briefly_unless_refreshed(sources, monkeypatch):
    monkeypatch.setattr(governance_engine, "_SCAN_TTL_SECONDS", 60)
    calls = []
    original = governance_engine._s3_source
    monkeypatch.setattr(governance_engine, "_s3_source", lambda refresh: calls.append(refresh) or original(refresh))
    first = governance_engine.collect()
    first["evaluations"].clear()  # callers get copies
    assert len(governance_engine.collect()["evaluations"]) == 1
    assert calls == [False]
    governance_engine.collect(refresh=True)
    assert calls == [False, True]


def test_sync_retries_after_a_concurrent_insert(sources, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    original = governance_engine._sync_rows
    attempts = []

    def flaky(*args):
        attempts.append(1)
        if len(attempts) == 1:
            raise IntegrityError("insert", {}, Exception("duplicate key"))
        return original(*args)

    monkeypatch.setattr(governance_engine, "_sync_rows", flaky)
    assert scan()[0]["lifecycle"]["persisted"] is True and len(attempts) == 2


def test_one_source_failing_does_not_break_others(sources):
    sources["fail"].add("ec2")
    result = governance_engine.collect()
    assert result["sources"]["ec2"]["status"] == "unavailable"
    assert result["sources"]["s3"]["status"] == "ok"


# --- endpoints -------------------------------------------------------------------


@pytest.fixture
def operator(monkeypatch, sources):
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDOPS_OPERATOR_EMAILS", "ops@example.com")
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"email": "ops@example.com", "password": PASSWORD})
    return client


def test_findings_endpoint_filters_and_sorts(operator, sources):
    sources["s3"] = [finding(), finding("S3_VERSIONING", POTENTIAL, "LOW", category="CONFIGURATION")]
    body = operator.get("/api/governance/findings").json()
    assert body["total"] == 2
    assert body["findings"][0]["rule_id"] == "S3_PUBLIC_POLICY"  # highest priority first
    assert operator.get("/api/governance/findings", params={"category": "configuration"}).json()["total"] == 1
    assert operator.get("/api/governance/findings", params={"severity": "bogus"}).status_code == 422


def test_summary_endpoint(operator):
    body = operator.get("/api/governance/summary").json()
    assert body["total_findings"] == 1
    assert body["by_severity"]["CRITICAL"] == 1
    assert body["by_category"]["SECURITY"] == 1
    assert body["top_priorities"][0]["priority"]["score"] == 70.0
    assert "formula" in body["scoring"]


def test_status_update_by_operator_is_audited(operator):
    fid = operator.get("/api/governance/findings").json()["findings"][0]["finding_id"]
    response = operator.patch("/api/governance/findings/%s" % fid, json={"status": "accepted_risk", "note": "demo bucket"})
    assert response.status_code == 200 and response.json()["finding_status"] == "accepted_risk"
    listed = operator.get("/api/governance/findings").json()["findings"][0]["lifecycle"]
    assert listed["status"] == "accepted_risk" and listed["status_note"] == "demo bucket"
    assert operator.patch("/api/governance/findings/nope", json={"status": "open"}).status_code == 404


def test_status_update_requires_operator(operator, monkeypatch):
    fid = operator.get("/api/governance/findings").json()["findings"][0]["finding_id"]
    other = TestClient(main.app)
    other.post("/api/auth/register", json={"email": "viewer@example.com", "password": PASSWORD})
    assert other.patch("/api/governance/findings/%s" % fid, json={"status": "false_positive"}).status_code == 403
    assert TestClient(main.app).patch("/api/governance/findings/%s" % fid, json={"status": "open"}).status_code == 401


def test_me_reports_operator_flag(operator):
    assert operator.get("/api/auth/me").json()["is_operator"] is True
    other = TestClient(main.app)
    other.post("/api/auth/register", json={"email": "viewer@example.com", "password": PASSWORD})
    assert other.get("/api/auth/me").json()["is_operator"] is False


def test_findings_are_private_by_default(sources):
    assert TestClient(main.app).get("/api/governance/findings").status_code == 401


def test_iac_endpoint_returns_scored_unified_findings():
    plan = {"resource_changes": [{"address": "aws_instance.web", "type": "aws_instance", "name": "web",
                                  "change": {"actions": ["update"], "before": {"instance_type": "t3.small"},
                                             "after": {"instance_type": "t3.large"}}}]}
    body = TestClient(main.app).post("/api/governance/iac", json={
        "plan": plan, "metrics": {"aws_instance.web": {"cpu_average": 3.0}}}).json()
    assert body["total_findings"] == 1
    item = body["findings"][0]
    assert item["rule_id"] == "IAC_OVERPROVISIONED_CHANGE" and item["evidence_state"] == POTENTIAL
    assert "score" in item["priority"]


def test_real_sources_against_moto(monkeypatch):
    """EC2 and S3 sources run end to end against moto without errors."""
    import boto3
    from moto import mock_aws

    from aws_client import _discovery_cache
    from services import s3_discovery

    for key, value in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                       "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(key, value)
    _discovery_cache.clear()
    s3_discovery.clear_cache()
    with mock_aws():
        ec2 = boto3.client("ec2")
        image = ec2.describe_images()["Images"][0]["ImageId"]
        ec2.run_instances(ImageId=image, MinCount=1, MaxCount=1, InstanceType="t3.micro")
        boto3.client("s3").create_bucket(Bucket="engine-bucket")
        result = governance_engine.collect(sources=["ec2", "s3"])
    _discovery_cache.clear()
    s3_discovery.clear_cache()
    assert result["sources"]["ec2"]["status"] == "ok", result["sources"]
    assert result["sources"]["s3"]["status"] == "ok", result["sources"]
    rules = {e["rule_id"] for e in result["evaluations"]}
    assert {"EC2_MISSING_OWNER_TAG", "EC2_LOW_UTILIZATION", "S3_DEFAULT_ENCRYPTION"} <= rules
