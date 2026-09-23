"""Unit tests for the deterministic decision engine.

These tests use mocked/sample structured data only. They never call AWS.
"""

from services.decision_engine import (
    analyze_ec2_resource,
    analyze_ec2_resources,
    analyze_iac_changes,
    normalize_metrics,
)


def make_instance(state="running", tags=None, instance_id="i-123", instance_type="t3.medium"):
    return {
        "InstanceId": instance_id,
        "InstanceType": instance_type,
        "State": {"Name": state},
        "Tags": [{"Key": key, "Value": value} for key, value in (tags or {}).items()],
    }


def issues(findings):
    return [finding["issue"] for finding in findings]


# ---------------------------------------------------------------------------
# Rule 1/2: stopped instance and missing Owner tag
# ---------------------------------------------------------------------------

def test_stopped_instance_finding():
    findings = analyze_ec2_resource(make_instance(state="stopped", tags={"Owner": "team-a"}))
    assert issues(findings) == ["Stopped EC2 instance"]
    assert findings[0]["severity"] == "medium"
    assert findings[0]["resource_id"] == "i-123"


def test_missing_owner_tag_finding():
    findings = analyze_ec2_resource(make_instance(tags={}))
    assert issues(findings) == ["Missing Owner tag"]
    assert findings[0]["severity"] == "low"


def test_stopped_and_missing_owner_produce_two_findings():
    findings = analyze_ec2_resource(make_instance(state="stopped", tags={}))
    assert set(issues(findings)) == {"Stopped EC2 instance", "Missing Owner tag"}


def test_tagged_running_instance_without_metrics_is_clean():
    findings = analyze_ec2_resource(make_instance(tags={"Owner": "team-a"}))
    assert findings == []


# ---------------------------------------------------------------------------
# Rule 3: underutilized EC2 (requires real metrics)
# ---------------------------------------------------------------------------

def test_underutilized_ec2_finding():
    metrics = {"cpu_average": 8.4, "cpu_max": 18.7, "period_hours": 24, "data_points": 24}
    findings = analyze_ec2_resource(make_instance(tags={"Owner": "team-a"}), metrics=metrics)
    assert issues(findings) == ["Potential EC2 underutilization"]
    assert findings[0]["severity"] == "medium"
    assert any("8.4" in item for item in findings[0]["evidence"])


def test_no_underutilization_without_metrics():
    findings = analyze_ec2_resource(make_instance(tags={"Owner": "team-a"}), metrics=None)
    assert findings == []


def test_no_underutilization_when_cpu_above_threshold():
    metrics = {"cpu_average": 40.0, "cpu_max": 60.0, "period_hours": 24, "data_points": 24}
    findings = analyze_ec2_resource(make_instance(tags={"Owner": "team-a"}), metrics=metrics)
    assert findings == []


def test_production_low_cpu_emphasizes_review_not_shutdown():
    metrics = {"cpu_average": 4.0, "cpu_max": 9.0, "period_hours": 24, "data_points": 24}
    findings = analyze_ec2_resource(
        make_instance(tags={"Owner": "team-a", "Environment": "production"}), metrics=metrics
    )
    assert issues(findings) == ["Potential EC2 underutilization"]
    recommendation = findings[0]["recommendation"].lower()
    assert "production" in recommendation
    assert "stop" not in recommendation


# ---------------------------------------------------------------------------
# Rule 4: high-cost + low-utilization (requires reliable cost)
# ---------------------------------------------------------------------------

def test_high_cost_low_utilization_finding():
    metrics = {"cpu_average": 5.0, "cpu_max": 12.0, "period_hours": 24, "data_points": 24}
    findings = analyze_ec2_resource(
        make_instance(tags={"Owner": "team-a"}), metrics=metrics, cost={"monthly_cost": 120.0}
    )
    assert "Potential high-cost underutilized resource" in issues(findings)
    high = [f for f in findings if f["severity"] == "high"]
    assert high and high[0]["issue"] == "Potential high-cost underutilized resource"


def test_high_cost_requires_low_utilization():
    metrics = {"cpu_average": 55.0, "cpu_max": 80.0, "period_hours": 24, "data_points": 24}
    findings = analyze_ec2_resource(
        make_instance(tags={"Owner": "team-a"}), metrics=metrics, cost={"monthly_cost": 120.0}
    )
    assert findings == []


def test_low_cost_does_not_trigger_high_cost_rule():
    metrics = {"cpu_average": 5.0, "cpu_max": 12.0, "period_hours": 24, "data_points": 24}
    findings = analyze_ec2_resource(
        make_instance(tags={"Owner": "team-a"}), metrics=metrics, cost={"monthly_cost": 5.0}
    )
    assert "Potential high-cost underutilized resource" not in issues(findings)


def test_analyze_many_instances_flattens_findings():
    instances = [
        make_instance(state="stopped", tags={"Owner": "a"}, instance_id="i-1"),
        make_instance(tags={}, instance_id="i-2"),
    ]
    findings = analyze_ec2_resources(instances)
    assert len(findings) == 2
    assert {finding["resource_id"] for finding in findings} == {"i-1", "i-2"}


# ---------------------------------------------------------------------------
# Phase 7: IaC decision logic
# ---------------------------------------------------------------------------

def make_instance_change(address, before_type, after_type, actions=None):
    return {
        "address": address,
        "resource_type": "aws_instance",
        "actions": actions or ["update"],
        "before": {"instance_type": before_type},
        "after": {"instance_type": after_type},
    }


def test_iac_capacity_increase_with_low_cpu_flags_review():
    change = make_instance_change("aws_instance.app", "t3.medium", "t3.2xlarge")
    metrics = {"aws_instance.app": {"cpu_average": 6.0}}
    infracost = {"status": "ok", "monthly_cost_change": 42.0}
    findings = analyze_iac_changes([change], metrics_by_address=metrics, infracost=infracost)
    assert len(findings) == 1
    assert findings[0]["issue"] == "Potential overprovisioning in infrastructure change"
    assert findings[0]["severity"] == "high"


def test_iac_capacity_increase_without_low_cpu_is_clean():
    change = make_instance_change("aws_instance.app", "t3.medium", "t3.2xlarge")
    metrics = {"aws_instance.app": {"cpu_average": 65.0}}
    findings = analyze_iac_changes([change], metrics_by_address=metrics)
    assert findings == []


def test_iac_downsize_is_not_flagged():
    change = make_instance_change("aws_instance.app", "t3.2xlarge", "t3.medium")
    metrics = {"aws_instance.app": {"cpu_average": 5.0}}
    findings = analyze_iac_changes([change], metrics_by_address=metrics)
    assert findings == []


# ---------------------------------------------------------------------------
# Metrics shape normalization (list vs. normalized dict vs. missing)
# ---------------------------------------------------------------------------

def test_normalize_metrics_accepts_list():
    normalized = normalize_metrics(
        [
            {
                "instance_id": "i-1",
                "period_hours": 24,
                "cpu_average": 8.4,
                "cpu_max": 18.7,
                "data_points": 24,
            }
        ]
    )
    assert normalized["i-1"]["cpu_average"] == 8.4
    assert normalized["i-1"]["cpu_max"] == 18.7


def test_normalize_metrics_accepts_dict():
    normalized = normalize_metrics({"i-2": {"cpu_average": 5.0}})
    assert normalized["i-2"]["cpu_average"] == 5.0


def test_normalize_metrics_accepts_resource_id_and_cpu_peak_alias():
    normalized = normalize_metrics(
        [{"resource_id": "aws_instance.app", "cpu_average": 3.0, "cpu_peak": 9.0}]
    )
    assert normalized["aws_instance.app"]["cpu_average"] == 3.0
    assert normalized["aws_instance.app"]["cpu_max"] == 9.0


def test_normalize_metrics_handles_missing_and_invalid():
    assert normalize_metrics(None) == {}
    assert normalize_metrics([]) == {}
    assert normalize_metrics(["not-a-record"]) == {}


def test_iac_analyze_accepts_metrics_as_list():
    """Reproduces the reported HTTP 500: metrics supplied as a list."""
    change = make_instance_change("aws_instance.app", "t3.medium", "t3.2xlarge")
    metrics = [
        {
            "instance_id": "aws_instance.app",
            "period_hours": 24,
            "cpu_average": 6.0,
            "cpu_max": 12.0,
            "data_points": 24,
        }
    ]
    infracost = {"status": "ok", "monthly_cost_change": 42.0}
    findings = analyze_iac_changes([change], metrics_by_address=metrics, infracost=infracost)
    assert len(findings) == 1
    assert findings[0]["issue"] == "Potential overprovisioning in infrastructure change"
    assert findings[0]["severity"] == "high"


def test_iac_analyze_accepts_normalized_metrics_dict():
    change = make_instance_change("aws_instance.app", "t3.medium", "t3.2xlarge")
    metrics = {"aws_instance.app": {"cpu_average": 6.0, "cpu_max": 12.0}}
    infracost = {"status": "ok", "monthly_cost_change": 5.0}
    findings = analyze_iac_changes([change], metrics_by_address=metrics, infracost=infracost)
    assert len(findings) == 1
    assert findings[0]["severity"] == "high"


def test_iac_analyze_missing_metrics_does_not_crash():
    change = make_instance_change("aws_instance.app", "t3.medium", "t3.2xlarge")
    infracost = {"status": "ok", "monthly_cost_change": 10.0}
    assert analyze_iac_changes([change], metrics_by_address=None, infracost=infracost) == []
    assert analyze_iac_changes([change], metrics_by_address=[], infracost=infracost) == []


def test_iac_analyze_list_metrics_without_cpu_is_clean():
    change = make_instance_change("aws_instance.app", "t3.medium", "t3.2xlarge")
    metrics = [{"instance_id": "aws_instance.app", "cpu_average": None, "data_points": 0}]
    assert analyze_iac_changes([change], metrics_by_address=metrics) == []


def test_iac_infracost_cost_and_governance_findings_are_deterministic():
    change = make_instance_change("aws_instance.cloudops_demo", "t3.medium", "t3.2xlarge")
    infracost = {
        "status": "ok",
        "currency": "USD",
        "planned_monthly_cost": 31.168,
        "monthly_cost_change": 5.0,
        "resources": [
            {
                "address": "aws_instance.cloudops_demo",
                "resource_type": "aws_instance",
                "monthly_cost": 31.168,
                "tags": {"Environment": "development"},
                "tagging_findings": [{"missing_mandatory_tags": ["Service"]}],
                "policy_findings": [{"finding": {"address": "aws_instance.cloudops_demo"}}],
            }
        ],
    }
    findings = analyze_iac_changes(
        [change],
        metrics_by_address={"aws_instance.cloudops_demo": {"cpu_average": 6.0}},
        infracost=infracost,
    )
    found_issues = {finding["issue"] for finding in findings}
    assert "Significant estimated monthly infrastructure cost" in found_issues
    assert "Estimated monthly infrastructure cost increase" in found_issues
    assert "Invalid or missing governance tags" in found_issues
    assert "Infrastructure policy violation" in found_issues
    assert "Potential high-cost underutilized resource" in found_issues
    assert "Potential overprovisioning in infrastructure change" in found_issues


def test_iac_real_scan_without_metrics_does_not_invent_utilization():
    change = make_instance_change("aws_instance.cloudops_demo", "t3.medium", "t3.2xlarge")
    infracost = {
        "status": "ok",
        "planned_monthly_cost": 31.168,
        "resources": [{"address": "aws_instance.cloudops_demo", "monthly_cost": 31.168}],
    }
    findings = analyze_iac_changes([change], metrics_by_address=None, infracost=infracost)
    assert "Potential high-cost underutilized resource" not in issues(findings)
    assert "Potential overprovisioning in infrastructure change" not in issues(findings)
