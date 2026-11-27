"""RDS discovery and governance tests (moto and constructed records)."""

import copy
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws

import main
from services import rds_discovery
from services.governance_common import (
    CONFIRMED,
    DATA_UNAVAILABLE,
    INSUFFICIENT_EVIDENCE,
    NO_ISSUE,
    POTENTIAL,
)
from services.rds_governance import evaluate_instance

GIB = 1024 ** 3


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_PUBLIC_SECURITY_FINDINGS", "true")
    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(key, value)
    rds_discovery.clear_cache()
    with mock_aws():
        yield
    rds_discovery.clear_cache()


def rules(db):
    return {e["rule_id"]: e for e in evaluate_instance(db)}


def record(**overrides):
    """A healthy, fully observed non-production database."""
    db = {
        "identifier": "db1", "engine": "postgres", "instance_class": "db.m6g.large",
        "status": "available", "region": "us-east-1", "multi_az": False,
        "publicly_accessible": False, "storage_encrypted": True, "storage_type": "gp3",
        "allocated_storage_gib": 50, "max_allocated_storage_gib": None,
        "backup_retention_days": 7, "deletion_protection": True,
        "tags": {"Environment": "development"},
        "security_groups": {"status": "ok", "open_to_internet": [], "group_ids": ["sg-1"]},
        "metrics": {
            "status": "ok", "window_days": 14, "expected_hours": 336, "observed_hours": 336,
            "coverage": 1.0, "cpu_mean": 35.0, "cpu_p95": 60.0, "cpu_peak": 85.0,
            "connections_peak": 40, "free_storage_bytes_latest": 25 * GIB,
            "free_storage_as_of": "2026-11-26T16:00:00+00:00",
            "freeable_memory_bytes_min": 2 * GIB, "note": None,
        },
    }
    for key, value in overrides.items():
        if key == "metrics":
            db["metrics"].update(value)
        else:
            db[key] = value
    return db


def create_db(identifier="db1", public=False, open_sg=False, tags=None, **extra):
    ec2, rds = boto3.client("ec2"), boto3.client("rds")
    sg = ec2.create_security_group(GroupName="sg-%s" % identifier, Description="db")["GroupId"]
    if open_sg:
        ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[{
            "IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432, "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        }])
    rds.create_db_instance(
        DBInstanceIdentifier=identifier, DBInstanceClass="db.t3.micro", Engine="postgres",
        MasterUsername="admin_user", MasterUserPassword="not-a-real-password", AllocatedStorage=20,
        PubliclyAccessible=public, VpcSecurityGroupIds=[sg],
        Tags=[{"Key": k, "Value": v} for k, v in (tags or {}).items()], **extra,
    )


def put_cpu(identifier, value, hours=336):
    cw = boto3.client("cloudwatch")
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    data = [{
        "MetricName": "CPUUtilization",
        "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": identifier}],
        "Timestamp": now - timedelta(hours=h) + timedelta(minutes=5), "Value": value,
    } for h in range(1, hours + 1)]
    for i in range(0, len(data), 500):
        cw.put_metric_data(Namespace="AWS/RDS", MetricData=data[i:i + 500])


# --- discovery (moto) --------------------------------------------------------


def test_empty_account():
    inventory = rds_discovery.discover_rds_instances()
    assert inventory["status"] == "ok" and inventory["total_instances"] == 0


def test_discovery_reads_configuration_security_groups_and_metrics():
    create_db(public=True, open_sg=True, tags={"Environment": "production"}, StorageType="gp2")
    put_cpu("db1", 3.0)
    db = rds_discovery.discover_rds_instances()["instances"][0]
    assert db["engine"] == "postgres" and db["port"] == 5432
    assert db["publicly_accessible"] is True and db["tags"] == {"Environment": "production"}
    assert db["security_groups"]["open_to_internet"][0]["cidrs"] == ["0.0.0.0/0"]
    assert db["metrics"]["observed_hours"] == 336 and db["metrics"]["coverage"] == 1.0
    assert db["metrics"]["cpu_mean"] == 3.0
    assert db["metrics"]["free_storage_bytes_latest"] is None  # absent, not zero


def test_production_scenario_end_to_end():
    create_db(public=True, open_sg=True, tags={"Environment": "production"}, StorageType="gp2")
    put_cpu("db1", 3.0)
    result = rules(rds_discovery.discover_rds_instances()["instances"][0])
    assert (result["RDS_PUBLIC_ACCESS"]["evidence_state"], result["RDS_PUBLIC_ACCESS"]["severity"]) == (CONFIRMED, "CRITICAL")
    assert result["RDS_STORAGE_ENCRYPTION"]["evidence_state"] == CONFIRMED
    assert result["RDS_MULTI_AZ"]["evidence_state"] == POTENTIAL
    assert result["RDS_GP2_STORAGE"]["evidence_state"] == POTENTIAL
    utilization = result["RDS_LOW_UTILIZATION"]
    # Production + low CPU: a review item with low confidence, never a resize order.
    assert utilization["evidence_state"] == POTENTIAL
    assert utilization["severity"] == "LOW" and utilization["confidence"] == "low"
    assert "production" in utilization["description"]
    assert any("Memory" in item for item in utilization["missing_information"])
    assert result["RDS_STORAGE_HEADROOM"]["evidence_state"] == INSUFFICIENT_EVIDENCE


def test_partial_metric_history_is_insufficient():
    create_db()
    put_cpu("db1", 2.0, hours=100)
    result = rules(rds_discovery.discover_rds_instances()["instances"][0])
    assert result["RDS_LOW_UTILIZATION"]["evidence_state"] == INSUFFICIENT_EVIDENCE


def test_metrics_use_one_get_metric_statistics_call_per_metric(monkeypatch):
    create_db()
    put_cpu("db1", 5.0, hours=24)
    cw = boto3.client("cloudwatch")
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    cw.put_metric_data(Namespace="AWS/RDS", MetricData=[{
        "MetricName": "FreeStorageSpace",
        "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": "db1"}],
        "Timestamp": now - timedelta(hours=h) + timedelta(minutes=5), "Value": float(10 - h),
    } for h in (1, 2)])
    calls = []
    real = rds_discovery.metric_series
    monkeypatch.setattr(rds_discovery, "metric_series", lambda *a: calls.append(a[2]) or real(*a))
    metrics = rds_discovery.discover_rds_instances()["instances"][0]["metrics"]
    assert calls == ["CPUUtilization", "DatabaseConnections", "FreeStorageSpace", "FreeableMemory"]
    assert metrics["observed_hours"] == 24 and metrics["cpu_peak"] == 5.0
    assert metrics["free_storage_bytes_latest"] == 9  # newest datapoint wins
    assert metrics["connections_peak"] is None and metrics["freeable_memory_bytes_min"] is None


def test_cloudwatch_denied_is_reported_not_zero(monkeypatch):
    create_db()

    def denied(*args, **kwargs):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetMetricStatistics")

    monkeypatch.setattr(rds_discovery, "metric_series", denied)
    db = rds_discovery.discover_rds_instances()["instances"][0]
    assert db["metrics"]["status"] == "access_denied"
    assert "cpu_mean" not in db["metrics"]
    assert rules(db)["RDS_LOW_UTILIZATION"]["evidence_state"] == DATA_UNAVAILABLE


def test_describe_denied_raises(monkeypatch):
    class Denied:
        meta = type("M", (), {"region_name": "us-east-1"})()

        def get_paginator(self, name):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "DescribeDBInstances")

    monkeypatch.setattr(rds_discovery, "_client", lambda service, region=None: Denied())
    with pytest.raises(rds_discovery.RDSAccessError) as error:
        rds_discovery.discover_rds_instances()
    assert "not permitted" in str(error.value)


# --- rules (constructed records) ---------------------------------------------


def test_healthy_database_has_no_findings():
    for evaluation in evaluate_instance(record()):
        assert evaluation["evidence_state"] == NO_ISSUE, evaluation["rule_id"]


def test_public_flag_with_closed_security_groups_is_potential():
    finding = rules(record(publicly_accessible=True))["RDS_PUBLIC_ACCESS"]
    assert (finding["evidence_state"], finding["severity"]) == (POTENTIAL, "MEDIUM")


def test_public_flag_with_unreadable_security_groups():
    db = record(publicly_accessible=True, security_groups={"status": "access_denied", "open_to_internet": None, "group_ids": ["sg-1"]})
    finding = rules(db)["RDS_PUBLIC_ACCESS"]
    assert (finding["evidence_state"], finding["severity"]) == (POTENTIAL, "HIGH")
    assert "ec2:DescribeSecurityGroups" in finding["missing_information"][0]


def test_backups_disabled_is_confirmed_high():
    finding = rules(record(backup_retention_days=0))["RDS_BACKUP_RETENTION"]
    assert (finding["evidence_state"], finding["severity"]) == (CONFIRMED, "HIGH")


def test_multi_az_needs_environment_context():
    assert rules(record(tags={}))["RDS_MULTI_AZ"]["evidence_state"] == INSUFFICIENT_EVIDENCE
    assert rules(record())["RDS_MULTI_AZ"]["evidence_state"] == NO_ISSUE
    assert rules(record(engine="aurora-postgresql"))["RDS_MULTI_AZ"]["evidence_state"] == INSUFFICIENT_EVIDENCE


def test_low_cpu_non_production_is_medium_confidence():
    finding = rules(record(metrics={"cpu_mean": 4.0, "cpu_p95": 8.0, "cpu_peak": 15.0}))["RDS_LOW_UTILIZATION"]
    assert (finding["evidence_state"], finding["severity"], finding["confidence"]) == (POTENTIAL, "MEDIUM", "medium")
    assert finding["potential_monthly_impact"] is None


def test_low_mean_but_spiky_cpu_is_not_flagged():
    finding = rules(record(metrics={"cpu_mean": 4.0, "cpu_p95": 8.0, "cpu_peak": 95.0}))["RDS_LOW_UTILIZATION"]
    assert finding["evidence_state"] == NO_ISSUE


def test_metrics_denied_is_data_unavailable_not_idle():
    db = record(metrics={"status": "access_denied"})
    result = rules(db)
    assert result["RDS_LOW_UTILIZATION"]["evidence_state"] == DATA_UNAVAILABLE
    assert result["RDS_STORAGE_HEADROOM"]["evidence_state"] == DATA_UNAVAILABLE


def test_storage_nearly_full():
    finding = rules(record(metrics={"free_storage_bytes_latest": 2 * GIB}))["RDS_STORAGE_HEADROOM"]
    assert (finding["evidence_state"], finding["severity"]) == (CONFIRMED, "HIGH")
    autoscaled = rules(record(max_allocated_storage_gib=200, metrics={"free_storage_bytes_latest": 2 * GIB}))
    assert autoscaled["RDS_STORAGE_HEADROOM"]["severity"] == "MEDIUM"


def test_large_mostly_empty_storage_is_low_potential():
    db = record(allocated_storage_gib=500, metrics={"free_storage_bytes_latest": 480 * GIB})
    finding = rules(db)["RDS_STORAGE_HEADROOM"]
    assert (finding["evidence_state"], finding["severity"]) == (POTENTIAL, "LOW")
    assert "cannot be shrunk" in finding["description"]


def test_stopped_database_is_not_judged_on_cpu():
    finding = rules(record(status="stopped", metrics={"cpu_mean": 0.5, "cpu_p95": 1.0, "cpu_peak": 2.0}))
    assert finding["RDS_LOW_UTILIZATION"]["evidence_state"] == INSUFFICIENT_EVIDENCE


def test_rules_do_not_mutate_input():
    db = record()
    before = copy.deepcopy(db)
    evaluate_instance(db)
    assert db == before


# --- endpoints ---------------------------------------------------------------


def test_rds_endpoints():
    create_db(public=True, open_sg=True, tags={"Environment": "production"})
    client = TestClient(main.app)
    listing = client.get("/api/resources/rds").json()
    assert listing["total_instances"] == 1
    assert listing["instances"][0]["governance"]["by_severity"]["CRITICAL"] == 1
    detail = client.get("/api/resources/rds/db1/governance").json()
    assert len(detail["evaluations"]) == 8
    assert detail["findings"][0]["rule_id"] == "RDS_PUBLIC_ACCESS"
    assert client.get("/api/resources/rds/missing/governance").status_code == 404


def test_rds_endpoints_are_private_by_default(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_PUBLIC_SECURITY_FINDINGS", "false")
    assert TestClient(main.app).get("/api/resources/rds").status_code == 401


def test_rds_endpoint_when_denied(monkeypatch):
    def denied(region=None, refresh=False):
        raise rds_discovery.RDSAccessError("RDS describe access is not permitted for the configured credentials.")

    monkeypatch.setattr(main, "discover_rds_instances", denied)
    response = TestClient(main.app).get("/api/resources/rds")
    assert response.status_code == 503 and response.json()["status"] == "unavailable"
