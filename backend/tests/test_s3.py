"""S3 discovery and governance tests against moto (no real AWS)."""

import json

import boto3
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws

import main
from services import s3_discovery, s3_governance
from services.s3_governance import (
    CONFIRMED,
    DATA_UNAVAILABLE,
    INSUFFICIENT_EVIDENCE,
    NO_ISSUE,
    POTENTIAL,
)

ALL_BPA = {
    "BlockPublicAcls": True,
    "IgnorePublicAcls": True,
    "BlockPublicPolicy": True,
    "RestrictPublicBuckets": True,
}


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_PUBLIC_SECURITY_FINDINGS", "true")
    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(key, value)
    s3_discovery.clear_cache()
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")
    s3_discovery.clear_cache()


def public_policy(bucket):
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow", "Principal": "*", "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::%s/*" % bucket,
        }],
    })


def by_rule(evaluations):
    return {e["rule_id"]: e for e in evaluations}


def evaluate(name, metrics=None):
    inventory = s3_discovery.discover_s3_buckets(refresh=True)
    bucket = next(b for b in inventory["buckets"] if b["name"] == name)
    if metrics is not None:
        bucket["metrics"] = metrics
    return by_rule(s3_governance.evaluate_bucket(bucket, inventory["account_public_access_block"]))


# --- discovery -------------------------------------------------------------


def test_empty_account_is_ok_not_error():
    inventory = s3_discovery.discover_s3_buckets()
    assert inventory["status"] == "ok"
    assert inventory["total_buckets"] == 0 and inventory["buckets"] == []


def test_discovers_regions_and_configuration(aws):
    aws.create_bucket(Bucket="alpha-bucket")
    aws.create_bucket(Bucket="beta-bucket", CreateBucketConfiguration={"LocationConstraint": "eu-west-2"})
    aws.put_bucket_versioning(Bucket="alpha-bucket", VersioningConfiguration={"Status": "Enabled"})
    aws.put_bucket_encryption(
        Bucket="alpha-bucket",
        ServerSideEncryptionConfiguration={"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]},
    )
    inventory = s3_discovery.discover_s3_buckets()
    buckets = {b["name"]: b for b in inventory["buckets"]}
    assert buckets["alpha-bucket"]["region"] == "us-east-1"
    assert buckets["beta-bucket"]["region"] == "eu-west-2"
    alpha = buckets["alpha-bucket"]["checks"]
    assert alpha["versioning"]["value"]["status"] == "Enabled"
    assert alpha["encryption"]["value"]["algorithms"] == ["AES256"]
    assert alpha["lifecycle"]["status"] == "not_configured"


def test_missing_metrics_are_null_not_zero(aws):
    aws.create_bucket(Bucket="alpha-bucket")
    metrics = s3_discovery.discover_s3_buckets()["buckets"][0]["metrics"]
    assert metrics["status"] == "no_data"
    assert metrics["standard_storage_bytes"] is None and metrics["object_count"] is None
    assert "does not mean zero" in metrics["note"]


def test_results_are_cached_and_refresh_has_cooldown(aws):
    aws.create_bucket(Bucket="alpha-bucket")
    first = s3_discovery.discover_s3_buckets()
    aws.create_bucket(Bucket="beta-bucket")
    assert s3_discovery.discover_s3_buckets()["total_buckets"] == 1
    # A refresh within the cooldown still returns the cached scan.
    assert s3_discovery.discover_s3_buckets(refresh=True)["scanned_at"] == first["scanned_at"]
    s3_discovery.clear_cache()
    assert s3_discovery.discover_s3_buckets()["total_buckets"] == 2


def test_list_denied_raises_clean_error(monkeypatch):
    class Denied:
        def get_paginator(self, name):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "ListBuckets")

    monkeypatch.setattr(s3_discovery, "_client", lambda service, region=None: Denied())
    with pytest.raises(s3_discovery.S3AccessError) as error:
        s3_discovery.discover_s3_buckets()
    assert "not permitted" in str(error.value)


def test_single_check_denied_is_reported_per_bucket(aws, monkeypatch):
    aws.create_bucket(Bucket="alpha-bucket")
    real_client = s3_discovery._client

    class DenyEncryption:
        def __init__(self, inner):
            self._inner = inner

        def get_bucket_encryption(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetBucketEncryption")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def client(service, region=None):
        inner = real_client(service, region)
        return DenyEncryption(inner) if service == "s3" else inner

    monkeypatch.setattr(s3_discovery, "_client", client)
    rules = evaluate("alpha-bucket")
    encryption = rules["S3_DEFAULT_ENCRYPTION"]
    assert encryption["evidence_state"] == DATA_UNAVAILABLE
    assert encryption["severity"] == "INFO"
    assert "s3:GetEncryptionConfiguration" in encryption["missing_information"][0]
    # Other checks still ran.
    assert rules["S3_VERSIONING"]["evidence_state"] == POTENTIAL


# --- governance rules --------------------------------------------------------


def test_public_policy_without_block_is_confirmed_critical(aws):
    aws.create_bucket(Bucket="public-bucket")
    aws.put_bucket_policy(Bucket="public-bucket", Policy=public_policy("public-bucket"))
    finding = evaluate("public-bucket")["S3_PUBLIC_POLICY"]
    assert finding["evidence_state"] == CONFIRMED and finding["severity"] == "CRITICAL"
    assert finding["category"] == "SECURITY"
    assert finding["requires_human_approval"] is True
    assert finding["potential_monthly_impact"] is None


def test_public_policy_restricted_by_bpa_is_potential(aws):
    aws.create_bucket(Bucket="public-bucket")
    aws.put_bucket_policy(Bucket="public-bucket", Policy=public_policy("public-bucket"))
    aws.put_public_access_block(Bucket="public-bucket", PublicAccessBlockConfiguration=ALL_BPA)
    rules = evaluate("public-bucket")
    assert rules["S3_PUBLIC_POLICY"]["evidence_state"] == POTENTIAL
    assert rules["S3_PUBLIC_POLICY"]["severity"] == "MEDIUM"
    assert rules["S3_BLOCK_PUBLIC_ACCESS"]["evidence_state"] == NO_ISSUE


def test_public_acl_is_confirmed_high(aws):
    aws.create_bucket(Bucket="acl-bucket")
    aws.put_bucket_acl(Bucket="acl-bucket", ACL="public-read")
    finding = evaluate("acl-bucket")["S3_PUBLIC_ACL"]
    assert finding["evidence_state"] == CONFIRMED and finding["severity"] == "HIGH"
    assert "READ" in finding["evidence"][0]["observation"]


def test_private_hardened_bucket_has_no_security_findings(aws):
    aws.create_bucket(Bucket="safe-bucket")
    aws.put_public_access_block(Bucket="safe-bucket", PublicAccessBlockConfiguration=ALL_BPA)
    aws.put_bucket_encryption(
        Bucket="safe-bucket",
        ServerSideEncryptionConfiguration={"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]},
    )
    rules = evaluate("safe-bucket")
    for rule_id in ("S3_PUBLIC_POLICY", "S3_PUBLIC_ACL", "S3_BLOCK_PUBLIC_ACCESS", "S3_DEFAULT_ENCRYPTION"):
        assert rules[rule_id]["evidence_state"] == NO_ISSUE, rule_id


def test_missing_encryption_is_confirmed(aws):
    aws.create_bucket(Bucket="plain-bucket")
    finding = evaluate("plain-bucket")["S3_DEFAULT_ENCRYPTION"]
    assert finding["evidence_state"] == CONFIRMED and finding["severity"] == "MEDIUM"


def test_lifecycle_unknown_size_is_insufficient_evidence(aws):
    aws.create_bucket(Bucket="data-bucket")
    finding = evaluate("data-bucket")["S3_LIFECYCLE"]
    assert finding["evidence_state"] == INSUFFICIENT_EVIDENCE
    assert "Current storage size." in finding["missing_information"]


def test_lifecycle_large_bucket_is_potential_with_size_evidence(aws):
    aws.create_bucket(Bucket="data-bucket")
    metrics = {"status": "ok", "standard_storage_bytes": 50 * 1024 ** 3, "object_count": 1000,
               "as_of": "2026-11-25T00:00:00+00:00", "note": None}
    finding = evaluate("data-bucket", metrics)["S3_LIFECYCLE"]
    assert finding["evidence_state"] == POTENTIAL and finding["category"] == "STORAGE"
    assert "50.0 GiB" in finding["evidence"][0]["observation"]
    assert finding["potential_monthly_impact"] is None  # never invented


def test_lifecycle_small_unversioned_bucket_is_no_issue(aws):
    aws.create_bucket(Bucket="data-bucket")
    metrics = {"status": "ok", "standard_storage_bytes": 2048, "object_count": 3, "as_of": None, "note": None}
    assert evaluate("data-bucket", metrics)["S3_LIFECYCLE"]["evidence_state"] == NO_ISSUE


def test_versioned_bucket_without_noncurrent_expiry_is_flagged(aws):
    aws.create_bucket(Bucket="data-bucket")
    aws.put_bucket_versioning(Bucket="data-bucket", VersioningConfiguration={"Status": "Enabled"})
    aws.put_bucket_lifecycle_configuration(
        Bucket="data-bucket",
        LifecycleConfiguration={"Rules": [{"ID": "tmp", "Status": "Enabled", "Filter": {"Prefix": "tmp/"}, "Expiration": {"Days": 7}}]},
    )
    finding = evaluate("data-bucket")["S3_LIFECYCLE"]
    assert finding["evidence_state"] == POTENTIAL
    assert "noncurrent" in finding["description"]


def test_every_rule_returns_exactly_one_state(aws):
    aws.create_bucket(Bucket="alpha-bucket")
    rules = evaluate("alpha-bucket")
    assert len(rules) == 7
    for evaluation in rules.values():
        assert evaluation["evidence_state"] in {CONFIRMED, POTENTIAL, INSUFFICIENT_EVIDENCE, NO_ISSUE, DATA_UNAVAILABLE}
        assert evaluation["evidence"], evaluation["rule_id"]


def test_finding_ids_are_stable(aws):
    aws.create_bucket(Bucket="alpha-bucket")
    first = evaluate("alpha-bucket")["S3_VERSIONING"]["finding_id"]
    s3_discovery.clear_cache()
    assert evaluate("alpha-bucket")["S3_VERSIONING"]["finding_id"] == first


# --- endpoints ---------------------------------------------------------------


def test_s3_endpoints(aws):
    aws.create_bucket(Bucket="public-bucket")
    aws.put_bucket_policy(Bucket="public-bucket", Policy=public_policy("public-bucket"))
    client = TestClient(main.app)

    listing = client.get("/api/resources/s3")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total_buckets"] == 1
    assert body["buckets"][0]["governance"]["by_severity"]["CRITICAL"] == 1

    detail = client.get("/api/resources/s3/public-bucket/governance").json()
    assert detail["status"] == "ok"
    assert len(detail["evaluations"]) == 7
    assert detail["findings"][0]["rule_id"] == "S3_PUBLIC_POLICY"

    missing = client.get("/api/resources/s3/not-a-bucket/governance")
    assert missing.status_code == 404


def test_s3_endpoint_when_listing_denied(monkeypatch):
    def denied(refresh=False):
        raise s3_discovery.S3AccessError("S3 bucket listing is not permitted for the configured credentials.")

    monkeypatch.setattr(main, "discover_s3_buckets", denied)
    response = TestClient(main.app).get("/api/resources/s3")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "error": "S3 bucket listing is not permitted for the configured credentials.",
    }


# --- access control -----------------------------------------------------------


def _signed_in(email):
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"email": email, "password": "correct horse battery"})
    return client


def test_s3_findings_are_private_by_default(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDOPS_PUBLIC_SECURITY_FINDINGS", "false")
    monkeypatch.setenv("CLOUDOPS_OPERATOR_EMAILS", "ops@example.com")
    assert TestClient(main.app).get("/api/resources/s3").status_code == 401
    assert _signed_in("someone@example.com").get("/api/resources/s3").status_code == 403
    operator = _signed_in("ops@example.com")
    response = operator.get("/api/resources/s3")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert operator.get("/api/resources/s3/none/governance").status_code == 404
