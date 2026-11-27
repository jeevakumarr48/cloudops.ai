"""HTTP contract tests for the existing public API.

These freeze the response shapes of the nine original endpoints so later
phases cannot silently break the deployed frontend. Every AWS-facing service
is replaced with a fake; no AWS call is made and no credential is needed.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from aws_client import AWSAccessError
from services.aws_metrics import MetricsUnavailableError
from services.cost_service import CostServiceError

INSTANCES = [
    {
        "InstanceId": "i-0abc",
        "InstanceType": "t3.large",
        "State": {"Name": "running"},
        "Placement": {"AvailabilityZone": "us-east-1a"},
        "LaunchTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "Tags": [{"Key": "Environment", "Value": "development"}],
    },
    {
        "InstanceId": "i-0def",
        "InstanceType": "t3.micro",
        "State": {"Name": "stopped"},
        "Placement": {"AvailabilityZone": "us-east-1b"},
        "LaunchTime": datetime(2026, 2, 1, tzinfo=timezone.utc),
        "Tags": [{"Key": "Owner", "Value": "jeeva"}],
    },
]

METRICS = [
    {"instance_id": "i-0abc", "period_hours": 24, "cpu_average": 4.2, "cpu_max": 9.0, "data_points": 24},
    {"instance_id": "i-0def", "period_hours": 24, "cpu_average": None, "cpu_max": None, "data_points": 0},
]

COST_SUMMARY = {
    "period": "monthly",
    "total_cost": 1.23,
    "currency": "USD",
    "start": "2026-11-01",
    "end": "2026-11-27",
    "end_inclusive": "2026-11-26",
    "services": [{"service": "Amazon EC2", "cost": 1.23}],
}

FORECAST = {
    "available": True,
    "period": "monthly",
    "start": "2026-11-27",
    "end": "2027-01-28",
    "mean": 2.5,
    "lower": 2.0,
    "upper": 3.0,
    "currency": "USD",
}


@pytest.fixture
def client(monkeypatch):
    # Response shapes are the contract under test; access control is tested in
    # test_legacy_endpoints_need_an_operator below.
    monkeypatch.setenv("CLOUDOPS_PUBLIC_SECURITY_FINDINGS", "true")
    monkeypatch.delenv("CLOUDOPS_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(main, "discover_ec2_instances", lambda region=None: list(INSTANCES))
    monkeypatch.setattr(
        main, "get_ec2_metrics", lambda ids, region_name=None, hours=24: list(METRICS)
    )
    monkeypatch.setattr(main, "get_cost_summary", lambda **kwargs: dict(COST_SUMMARY))
    monkeypatch.setattr(main, "get_cost_forecast", lambda **kwargs: dict(FORECAST))
    return TestClient(main.app)


def _deny(*args, **kwargs):
    raise AWSAccessError("Failed to retrieve EC2 instances")


def test_root_and_health(client):
    assert client.get("/").json() == {"message": "CloudOps AI API is running", "status": "healthy"}
    assert client.get("/health").json() == {"status": "healthy"}


def test_ec2_resources_shape(client):
    body = client.get("/api/resources/ec2").json()
    assert set(body) == {"total_instances", "instances"}
    assert body["total_instances"] == 2
    assert set(body["instances"][0]) == {
        "instance_id", "instance_type", "state", "availability_zone", "launch_time", "tags",
    }
    assert body["instances"][0]["tags"] == {"Environment": "development"}


def test_ec2_metrics_shape(client):
    body = client.get("/api/metrics/ec2").json()
    assert set(body) == {"total_instances", "period_hours", "metrics"}
    assert body["period_hours"] == 24
    assert body["metrics"][1]["cpu_average"] is None


def test_costs_and_forecast_shapes(client):
    assert client.get("/api/costs").json() == COST_SUMMARY
    assert client.get("/api/costs/forecast").json() == FORECAST


def test_insights_shape(client):
    body = client.get("/api/insights").json()
    assert set(body) == {
        "status", "metrics_status", "total_findings", "by_severity", "findings", "explanation",
    }
    assert body["status"] == "ok" and body["metrics_status"] == "ok"
    assert set(body["by_severity"]) == {"high", "medium", "low"}
    issues = {finding["issue"] for finding in body["findings"]}
    assert "Potential EC2 underutilization" in issues
    assert body["explanation"]["source"] == "deterministic"


def test_overview_shape(client):
    body = client.get("/api/overview").json()
    assert set(body) == {"resources", "cost", "insights"}
    assert body["resources"] == {
        "status": "ok", "total_instances": 2, "by_state": {"running": 1, "stopped": 1},
    }
    assert body["cost"] == COST_SUMMARY
    assert set(body["insights"]) == {"status", "metrics_status", "total_findings", "by_severity"}


def test_recommendations_shape(client):
    body = client.get("/api/recommendations").json()
    assert set(body) == {"total_recommendations", "recommendations"}
    assert set(body["recommendations"][0]) == {
        "resource_id", "resource_type", "severity", "issue", "recommendation",
        "estimated_monthly_savings", "tags",
    }


def test_iac_analyze_shape(client):
    plan = {
        "resource_changes": [
            {
                "address": "aws_instance.web",
                "type": "aws_instance",
                "name": "web",
                "change": {
                    "actions": ["update"],
                    "before": {"instance_type": "t3.small"},
                    "after": {"instance_type": "t3.large"},
                },
            }
        ]
    }
    body = client.post(
        "/api/iac/analyze",
        json={"plan": plan, "metrics": {"aws_instance.web": {"cpu_average": 3.0}}},
    ).json()
    assert set(body) == {"status", "changes", "infracost", "total_findings", "findings", "explanation"}
    assert body["findings"][0]["issue"] == "Potential overprovisioning in infrastructure change"


def test_iac_analyze_requires_plan(client):
    response = client.post("/api/iac/analyze", json={})
    assert response.status_code == 400
    assert response.json()["status"] == "error"


def test_ec2_access_failure_is_503(client, monkeypatch):
    monkeypatch.setattr(main, "discover_ec2_instances", _deny)
    response = client.get("/api/resources/ec2")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "error": "Failed to retrieve EC2 instances"}


def test_cost_failure_is_503(client, monkeypatch):
    def fail(**kwargs):
        raise CostServiceError("Cost Explorer access denied for the configured credentials.")

    monkeypatch.setattr(main, "get_cost_summary", fail)
    response = client.get("/api/costs")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


def test_insights_metrics_failure_is_reported(client, monkeypatch):
    def fail(*args, **kwargs):
        raise MetricsUnavailableError("Failed to retrieve EC2 CloudWatch metrics")

    monkeypatch.setattr(main, "get_ec2_metrics", fail)
    body = client.get("/api/insights").json()
    assert body["metrics_status"] == "unavailable"
    assert body["metrics_error"] == "Failed to retrieve EC2 CloudWatch metrics"


# --- Phase 1 hardening -----------------------------------------------------


def test_overview_reports_ec2_failure_as_message(client, monkeypatch):
    monkeypatch.setattr(main, "discover_ec2_instances", _deny)
    response = client.get("/api/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["resources"] == {
        "status": "unavailable",
        "error": "Failed to retrieve EC2 instances",
    }
    assert body["insights"] == {"status": "unavailable"}
    assert "cache-control" not in response.headers


@pytest.mark.parametrize("path", ["/api/metrics/ec2", "/api/insights", "/api/overview"])
@pytest.mark.parametrize("hours", [0, -5, 721, 99999999])
def test_hours_out_of_range_is_rejected(client, path, hours):
    assert client.get(path, params={"hours": hours}).status_code == 422


@pytest.mark.parametrize("path", ["/api/metrics/ec2", "/api/insights", "/api/overview"])
def test_hours_in_range_is_accepted(client, path):
    assert client.get(path, params={"hours": 720}).status_code == 200


def test_successful_cost_responses_are_cdn_cacheable(client):
    for path in ("/api/costs", "/api/costs/forecast"):
        header = client.get(path).headers["cache-control"]
        assert header.startswith("public, max-age=0, s-maxage=")
        seconds = int(header.split("s-maxage=")[1].split(",")[0])
        assert 60 <= seconds <= main._seconds_until_utc_midnight() + 1


def test_failed_responses_are_not_cached(client, monkeypatch):
    def fail(**kwargs):
        raise CostServiceError("Failed to reach Cost Explorer.")

    monkeypatch.setattr(main, "get_cost_summary", fail)
    assert "cache-control" not in client.get("/api/costs").headers
    monkeypatch.setattr(main, "discover_ec2_instances", _deny)
    assert "cache-control" not in client.get("/api/resources/ec2").headers


LIVE_AWS_PATHS = ("/api/resources/ec2", "/api/metrics/ec2", "/api/costs", "/api/costs/forecast",
                  "/api/insights", "/api/overview", "/api/recommendations")


@pytest.mark.parametrize("path", LIVE_AWS_PATHS)
def test_legacy_endpoints_need_an_operator(monkeypatch, path):
    monkeypatch.setattr(main, "discover_ec2_instances", lambda region=None: list(INSTANCES))
    monkeypatch.setattr(main, "get_cost_summary", lambda **kwargs: dict(COST_SUMMARY))
    response = TestClient(main.app).get(path)
    assert response.status_code == 401 and response.json()["code"] == "unauthenticated"


def test_signed_in_cost_responses_are_never_shared_by_the_cdn(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDOPS_OPERATOR_EMAILS", "ops@example.com")
    monkeypatch.setattr(main, "get_cost_summary", lambda **kwargs: dict(COST_SUMMARY))
    operator = TestClient(main.app)
    operator.post("/api/auth/register", json={"email": "ops@example.com", "password": "correct horse battery"})
    response = operator.get("/api/costs")
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
