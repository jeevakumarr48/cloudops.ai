"""Unit tests for Terraform plan parsing and Infracost normalization."""

import json
from pathlib import Path

import pytest

from services.iac_analyzer import (
    IaCPlanError,
    load_infracost_file,
    infracost_status,
    load_plan_file,
    normalize_infracost,
    parse_plan,
)
from services.decision_engine import analyze_iac_changes


def plan_with(actions, resource_type="aws_instance", address="aws_instance.app"):
    return {
        "resource_changes": [
            {
                "address": address,
                "type": resource_type,
                "name": "app",
                "change": {
                    "actions": actions,
                    "before": {"instance_type": "t3.medium"},
                    "after": {"instance_type": "t3.medium"},
                },
            }
        ]
    }


def test_parse_create_change():
    changes = parse_plan(plan_with(["create"]))["changes"]
    assert len(changes) == 1
    assert changes[0]["actions"] == ["create"]
    assert changes[0]["address"] == "aws_instance.app"
    assert changes[0]["resource_type"] == "aws_instance"


def test_parse_update_change():
    changes = parse_plan(plan_with(["update"]))["changes"]
    assert changes[0]["actions"] == ["update"]


def test_parse_delete_change():
    changes = parse_plan(plan_with(["delete"]))["changes"]
    assert changes[0]["actions"] == ["delete"]


def test_parse_replace_collapses_delete_create():
    changes = parse_plan(plan_with(["delete", "create"]))["changes"]
    assert changes[0]["actions"] == ["replace"]


def test_parse_plan_empty_changes():
    assert parse_plan({})["changes"] == []


def test_parse_plan_rejects_non_object():
    with pytest.raises(IaCPlanError):
        parse_plan(["not", "a", "plan"])


def test_load_plan_file_reads_json(tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan_with(["create"])), encoding="utf-8")
    changes = load_plan_file(str(plan_file))["changes"]
    assert changes[0]["actions"] == ["create"]


def test_load_plan_file_missing_raises(tmp_path):
    with pytest.raises(IaCPlanError):
        load_plan_file(str(tmp_path / "does-not-exist.json"))


def test_load_plan_file_invalid_json_raises(tmp_path):
    bad_file = tmp_path / "plan.json"
    bad_file.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(IaCPlanError):
        load_plan_file(str(bad_file))


def test_normalize_infracost_breakdown():
    result = normalize_infracost({"totalMonthlyCost": "123.45", "currency": "USD"})
    assert result["status"] == "ok"
    assert result["planned_monthly_cost"] == 123.45
    assert result["currency"] == "USD"


def test_normalize_infracost_diff():
    result = normalize_infracost(
        {"diff": {"totalMonthlyCost": "10.5", "totalMonthlyCostBefore": "100", "currency": "USD"}}
    )
    assert result["status"] == "ok"
    assert result["monthly_cost_change"] == 10.5
    assert result["planned_monthly_cost"] == 110.5


def test_normalize_infracost_without_cost_data_is_not_configured():
    assert normalize_infracost({})["status"] == "not_configured"
    assert normalize_infracost(None)["status"] == "not_configured"


def real_infracost_scan():
    return {
        "currency": "USD",
        "total_monthly_cost": "31.168",
        "resources": [
            {
                "address": "aws_instance.cloudops_demo",
                "resource_type": "aws_instance",
                "base_monthly_cost": "30.00",
                "usage_monthly_cost": "1.168",
                "total_monthly_cost": "31.168",
                "cost_components": [{"name": "instance", "monthly_cost": "30.00"}],
                "tags": {"Environment": "development", "Owner": "CloudOps-AI"},
                "metadata": {"region": "us-east-1"},
            },
            {
                "address": "aws_instance.free_demo",
                "resource_type": "aws_instance",
                "cost_components": [],
            },
        ],
        "failing_tagging": [
            {
                "address": "aws_instance.cloudops_demo",
                "resource_type": "aws_instance",
                "invalid_tags": [{"key": "Environment", "value": "development"}],
                "missing_mandatory_tags": ["Service"],
            }
        ],
        "failing_policy_list": [
            {
                "kind": "finops",
                "name": "No public IPv4",
                "failing_finops": [
                    {
                        "address": "aws_instance.cloudops_demo",
                        "issues": [{"description": "Disable public IP"}],
                    }
                ],
            }
        ],
    }


def test_normalize_real_infracost_scan_resources_and_findings():
    result = normalize_infracost(real_infracost_scan())
    assert result["status"] == "ok"
    assert result["planned_monthly_cost"] == 31.168
    assert len(result["resources"]) == 2
    resource = result["resources"][0]
    assert resource["address"] == "aws_instance.cloudops_demo"
    assert resource["resource_type"] == "aws_instance"
    assert resource["monthly_cost"] == 31.168
    assert resource["base_monthly_cost"] == 30.0
    assert resource["usage_monthly_cost"] == 1.168
    assert resource["tags"]["Environment"] == "development"
    assert resource["metadata"]["region"] == "us-east-1"
    assert resource["tagging_findings"][0]["missing_mandatory_tags"] == ["Service"]
    assert resource["policy_findings"][0]["finding"]["address"] == "aws_instance.cloudops_demo"


def test_normalize_checked_in_real_infracost_v2163_scan():
    scan_path = Path(__file__).parents[2] / "infrastructure" / "infracost-scan.json"
    result = load_infracost_file(str(scan_path))

    assert result["status"] == "ok"
    assert result["currency"] == "USD"
    assert result["planned_monthly_cost"] == 31.168
    resource = result["resources"][0]
    assert resource["name"] == "aws_instance.cloudops_demo"
    assert resource["resource_type"] == "aws_instance"
    assert resource["monthly_cost"] == 30.368
    assert resource["cost_components"][0]["total_monthly_cost"] == "30.368"
    assert resource["subresources"][0]["name"] == "root_block_device"
    assert resource["is_supported"] is True
    assert resource["is_free"] is False
    assert resource["supports_tags"] is True
    assert resource["supports_default_tags"] is True
    assert resource["tags"]["Owner"] == "CloudOps-AI"


def test_normalize_real_resource_falls_back_to_component_totals():
    result = normalize_infracost({
        "currency": "EUR",
        "projects": [{
            "resources": [{
                "name": "aws_instance.app",
                "type": "aws_instance",
                "cost_components": [
                    {"total_monthly_cost": "12.50"},
                    {"total_monthly_cost": "7.25"},
                ],
            }],
        }],
    })

    assert result["currency"] == "EUR"
    assert result["planned_monthly_cost"] == 19.75
    assert result["resources"][0]["monthly_cost"] == 19.75


def test_real_shaped_infracost_diff_drives_cost_increase_finding():
    change = plan_with(["update"])["resource_changes"]
    infracost = normalize_infracost({
        "currency": "USD",
        "diff": {
            "totalMonthlyCostBefore": "31.168",
            "totalMonthlyCost": "41.168",
        },
        "projects": [{
            "resources": [{
                "name": "aws_instance.app",
                "type": "aws_instance",
                "is_supported": True,
                "is_free": False,
                "cost_components": [{"total_monthly_cost": "41.168"}],
            }],
        }],
    })
    findings = analyze_iac_changes(
        parse_plan({"resource_changes": change})["changes"],
        infracost=infracost,
    )

    assert "Estimated monthly infrastructure cost increase" in {
        finding["issue"] for finding in findings
    }


def test_normalize_infracost_missing_resource_cost_fields_is_safe():
    result = normalize_infracost({"resources": [{"address": "aws_instance.unknown"}]})
    assert result["status"] == "ok"
    assert result["resources"][0]["monthly_cost"] is None
    assert result["planned_monthly_cost"] is None


def test_infracost_status_not_configured(monkeypatch):
    monkeypatch.delenv("INFRACOST_API_KEY", raising=False)
    assert infracost_status()["status"] == "not_configured"


def test_infracost_status_configured(monkeypatch):
    monkeypatch.setenv("INFRACOST_API_KEY", "test-key")
    assert infracost_status()["status"] == "configured"
