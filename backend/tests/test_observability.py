"""Structured logs, request metrics, readiness and the ops status page."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

import main
from core import observability
from core.database import session_factory
from core.models import ScanRun
from services import governance_engine

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def fresh_stats():
    observability.stats.reset()
    yield


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDOPS_OPERATOR_EMAILS", "ops@example.com")
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"email": "ops@example.com", "password": PASSWORD})
    return client


def test_json_formatter_includes_request_id_and_extras():
    record = logging.LogRecord("cloudops.test", logging.INFO, __file__, 1, "scan took %dms", (42,), None)
    record.duration_ms = 42
    token = observability.request_id_var.set("abc123")
    try:
        line = json.loads(observability.JsonFormatter().format(record))
    finally:
        observability.request_id_var.reset(token)
    assert line["message"] == "scan took 42ms" and line["request_id"] == "abc123"
    assert line["duration_ms"] == 42 and line["level"] == "INFO" and line["time"].endswith("+00:00")


def test_log_format_defaults(monkeypatch):
    monkeypatch.delenv("CLOUDOPS_LOG_FORMAT", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    assert observability.log_format() == "text"
    monkeypatch.setenv("VERCEL", "1")
    assert observability.log_format() == "json"
    monkeypatch.setenv("CLOUDOPS_LOG_FORMAT", "text")
    assert observability.log_format() == "text"


def test_requests_are_counted_by_route_template_without_ids(monkeypatch):
    client = TestClient(main.app)
    client.get("/health")
    client.get("/api/governance/findings/abc-secret-id-123")
    snap = observability.stats.snapshot()
    routes = {r["route"] for r in snap["top_routes"]}
    assert "/health" in routes
    assert not any("abc-secret-id-123" in r for r in routes)
    assert snap["total_requests"] == 2 and snap["latency_ms"]["samples"] == 2


def test_access_log_never_contains_query_strings_or_bodies(caplog):
    caplog.set_level(logging.INFO, logger="cloudops.access")
    TestClient(main.app).post("/api/auth/login?token=leak", json={"email": "a@b.co", "password": "hunter2-secret"})
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "/api/auth/login" in text and "leak" not in text and "hunter2" not in text


def test_server_errors_are_counted(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_PUBLIC_SECURITY_FINDINGS", "true")
    monkeypatch.setattr(main, "discover_ec2_instances", lambda region=None: (_ for _ in ()).throw(RuntimeError("boom")))
    TestClient(main.app, raise_server_exceptions=False).get("/api/resources/ec2")
    assert observability.stats.snapshot()["server_errors"] == 1


def test_readiness_reports_database():
    response = TestClient(main.app).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}
    assert response.headers["cache-control"] == "no-store"


def test_scans_are_recorded_with_per_source_timing(monkeypatch):
    monkeypatch.setattr(governance_engine, "_s3_source", lambda refresh: [])
    monkeypatch.setattr(governance_engine, "_ec2_source", lambda refresh: [])
    monkeypatch.setattr(governance_engine, "_rds_source", lambda refresh: [])

    def cost_down(refresh):
        from services.cost_service import CostServiceError
        raise CostServiceError("Failed to reach Cost Explorer.")
    monkeypatch.setattr(governance_engine, "_cost_source", cost_down)
    governance_engine.collect(refresh=True)
    db = session_factory()()
    try:
        row = db.query(ScanRun).one()
        assert row.sources["cost"]["status"] == "unavailable" and row.sources["cost"]["error"] is True
        assert isinstance(row.sources["s3"]["duration_ms"], int)
    finally:
        db.close()


def test_scan_history_is_pruned(monkeypatch):
    monkeypatch.setattr(governance_engine, "SCAN_HISTORY", 3)
    for name in ("_s3_source", "_ec2_source", "_rds_source", "_cost_source"):
        monkeypatch.setattr(governance_engine, name, lambda refresh: [])
    for _ in range(5):
        governance_engine.collect(refresh=True)
    db = session_factory()()
    try:
        assert db.query(ScanRun).count() == 3
    finally:
        db.close()


def test_ops_status_is_operator_only_and_has_no_secrets(operator, monkeypatch):
    monkeypatch.setenv("CLOUDOPS_AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLOUDOPS_AI_API_KEY", "sk-should-not-appear")
    assert TestClient(main.app).get("/api/ops/status").status_code == 401
    for name in ("_s3_source", "_ec2_source", "_rds_source", "_cost_source"):
        monkeypatch.setattr(governance_engine, name, lambda refresh: [])
    governance_engine.collect(refresh=True)
    body = operator.get("/api/ops/status").json()
    assert body["checks"]["database"]["status"] == "ok" and body["checks"]["ai_provider"] == "openai_compatible"
    assert body["budgets"]["cost_explorer_requests_this_month"]["limit"] == 75
    assert body["scans"]["recent"] and body["scans"]["by_source"]["s3"]["success_rate"] == 1.0
    assert body["requests"]["scope"] == "this instance since it started"
    assert "sk-should-not-appear" not in json.dumps(body)



def test_access_log_carries_the_request_id():
    import io
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(observability.JsonFormatter())
    access = logging.getLogger("cloudops.access")
    access.addHandler(handler)
    previous = access.level
    access.setLevel(logging.INFO)
    try:
        response = TestClient(main.app).get("/api/demo/ai/status")
    finally:
        access.removeHandler(handler)
        access.setLevel(previous)
    line = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert line["request_id"] == response.headers["x-request-id"]
    assert line["route"] == "/api/demo/ai/status" and line["status"] == 200


def test_unavailable_dependencies_are_not_counted_as_crashes():
    observability.stats.record("/api/costs", 503, 5.0)
    observability.stats.record("/api/costs", 500, 5.0)
    snap = observability.stats.snapshot()
    assert snap["server_errors"] == 1 and snap["dependency_unavailable"] == 1
