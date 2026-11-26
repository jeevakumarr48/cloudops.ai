"""Phase 9: origin check, headers, error envelope, audit view, role-based AWS access."""

from datetime import datetime, timedelta, timezone

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

import main
from core import aws_session

PASSWORD = "correct horse battery"


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDOPS_OPERATOR_EMAILS", "ops@example.com")
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"email": "ops@example.com", "password": PASSWORD})
    return client


@pytest.fixture(autouse=True)
def clean_aws(monkeypatch):
    for key in ("CLOUDOPS_AWS_AUTH", "CLOUDOPS_AWS_ROLE_ARN", "CLOUDOPS_AWS_EXTERNAL_ID", "VERCEL_OIDC_TOKEN", "VERCEL_OIDC_TOKEN_FILE"):
        monkeypatch.delenv(key, raising=False)
    aws_session.clear_cache()
    yield
    aws_session.clear_cache()


# --- origin check ----------------------------------------------------------------


def test_cross_site_write_with_cookie_is_blocked(operator):
    evil = operator.post("/api/auth/logout", json={}, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403 and evil.json()["code"] == "origin_not_allowed"
    assert operator.get("/api/auth/me").status_code == 200  # still signed in


def test_allowed_and_same_origin_writes_pass(operator):
    assert operator.post("/api/ai/analyze", json={}, headers={"Origin": "http://localhost:5173"}).status_code == 200
    assert operator.post("/api/ai/analyze", json={}, headers={"Origin": "http://testserver"}).status_code == 200
    assert operator.post("/api/ai/analyze", json={}).status_code == 200  # no Origin: not a browser form


def test_cross_site_fetch_metadata_without_origin_is_blocked(operator):
    response = operator.post("/api/ai/analyze", json={}, headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_anonymous_public_posts_are_unaffected():
    plan = {"resource_changes": []}
    response = TestClient(main.app).post("/api/iac/analyze", json={"plan": plan}, headers={"Origin": "https://evil.example"})
    assert response.status_code != 403


# --- headers and envelope --------------------------------------------------------


def test_security_headers_and_request_id():
    response = TestClient(main.app).get("/health")
    for header in ("X-Request-ID", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy"):
        assert header in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_docs_page_keeps_working():
    response = TestClient(main.app).get("/docs")
    assert response.status_code == 200 and "Content-Security-Policy" not in response.headers


def test_error_envelope_keeps_detail():
    body = TestClient(main.app).get("/api/governance/findings").json()
    assert body["status"] == "error" and body["code"] == "unauthenticated"
    assert body["detail"] == body["error"] and body["request_id"]


def test_validation_errors_use_envelope(operator):
    body = operator.post("/api/ai/analyze", json={"limit": 99}).json()
    assert body["code"] == "validation_error" and isinstance(body["detail"], list)


def test_legacy_error_shape_unchanged(monkeypatch):
    from aws_client import AWSAccessError
    monkeypatch.setattr(main, "discover_ec2_instances", lambda region=None: (_ for _ in ()).throw(AWSAccessError("no access")))
    body = TestClient(main.app).get("/api/resources/ec2").json()
    assert body["status"] in ("unavailable", "error") and isinstance(body["error"], str)


def test_unhandled_errors_do_not_leak(monkeypatch):
    monkeypatch.setattr(main, "discover_ec2_instances", lambda region=None: (_ for _ in ()).throw(RuntimeError("secret=abc123")))
    response = TestClient(main.app, raise_server_exceptions=False).get("/api/resources/ec2")
    assert response.status_code == 500 and "abc123" not in response.text and response.json()["code"] == "internal_error"


# --- operator views --------------------------------------------------------------


def test_audit_log_requires_operator_and_lists_events(operator):
    assert TestClient(main.app).get("/api/security/audit").status_code == 401
    other = TestClient(main.app)
    other.post("/api/auth/register", json={"email": "viewer@example.com", "password": PASSWORD})
    assert other.get("/api/security/audit").status_code == 403
    events = operator.get("/api/security/audit").json()["events"]
    assert {"user.register"} <= {e["action"] for e in events}
    assert all("password" not in str(e).lower() for e in events)
    assert operator.get("/api/security/audit", params={"action": "user.register"}).json()["total"] == 2


def test_security_status_never_returns_keys(operator, monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLEKEY123456")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "very-secret")
    body = operator.get("/api/security/status").json()
    creds = body["aws_credentials"]
    assert creds["mode"] == "default" and creds["temporary"] is False and creds["recommendation"]
    assert "AKIAEXAMPLEKEY123456" not in str(body) and "very-secret" not in str(body)


# --- role-based AWS access ---------------------------------------------------------


@pytest.fixture
def aws_env(monkeypatch):
    for key, value in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CLOUDOPS_AWS_ROLE_ARN", "arn:aws:iam::123456789012:role/cloudops-readonly")


def test_mode_selection(monkeypatch, aws_env):
    assert aws_session.mode() == "assume_role"
    aws_session.remember_oidc_token("header.jwt.token")
    assert aws_session.mode() == "oidc"
    monkeypatch.setenv("CLOUDOPS_AWS_AUTH", "default")
    assert aws_session.mode() == "default"


def test_default_mode_without_role(monkeypatch):
    monkeypatch.delenv("CLOUDOPS_AWS_ROLE_ARN", raising=False)
    assert aws_session.mode() == "default"


def test_assume_role_uses_temporary_credentials_and_caches(aws_env, monkeypatch):
    calls = []
    real_client = boto3.client

    class FakeSTS:
        def assume_role(self, **kwargs):
            calls.append(kwargs)
            return {"Credentials": {"AccessKeyId": "ASIATEMP", "SecretAccessKey": "s", "SessionToken": "t",
                                    "Expiration": datetime.now(timezone.utc) + timedelta(hours=1)}}

    monkeypatch.setenv("CLOUDOPS_AWS_EXTERNAL_ID", "ext-123")
    monkeypatch.setattr(aws_session.boto3, "client", lambda service, **kw: FakeSTS() if service == "sts" else real_client(service, **kw))
    creds = aws_session.session().get_credentials().get_frozen_credentials()
    assert creds.access_key == "ASIATEMP" and creds.token == "t"
    aws_session.session()
    assert len(calls) == 1 and calls[0]["ExternalId"] == "ext-123"
    assert aws_session.describe()["temporary"] is True


def test_oidc_exchanges_the_vercel_token(aws_env):
    aws_session.remember_oidc_token("eyJ.fake.token")
    with mock_aws():
        creds = aws_session.session().get_credentials().get_frozen_credentials()
        assert creds.token  # temporary credentials from AssumeRoleWithWebIdentity
        boto3_client = aws_session.client("s3", region_name="us-east-1")
        assert boto3_client.list_buckets()["Buckets"] == []


def test_oidc_header_is_captured_by_middleware(aws_env):
    TestClient(main.app).get("/health", headers={"x-vercel-oidc-token": "tok-from-header"})
    assert aws_session._oidc_token() == "tok-from-header"


def test_assume_role_failure_is_safe(aws_env, monkeypatch):
    class Denied:
        def assume_role(self, **kwargs):
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "arn:aws:iam::123456789012:user/x secret"}}, "AssumeRole")

    monkeypatch.setattr(aws_session.boto3, "client", lambda service, **kw: Denied())
    with pytest.raises(aws_session.AWSCredentialError) as error:
        aws_session.session()
    assert "AccessDenied" in str(error.value) and "secret" not in str(error.value)


def test_role_failure_makes_sources_unavailable_not_500(aws_env, monkeypatch, operator):
    class Denied:
        def assume_role(self, **kwargs):
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "AssumeRole")

    monkeypatch.setattr(aws_session.boto3, "client", lambda service, **kw: Denied())
    import aws_client
    aws_client._discovery_cache.clear()
    response = operator.get("/api/resources/ec2")
    assert response.status_code == 503 and response.json()["status"] == "unavailable"
    sources = operator.get("/api/governance/summary").json()["sources"]
    assert sources["ec2"]["status"] == "unavailable" and sources["s3"]["status"] == "unavailable"
