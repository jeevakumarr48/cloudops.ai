"""Public demo endpoints: sample data only, no AWS, no database writes, no AI."""

import pytest
from fastapi.testclient import TestClient

import main
from core.database import session_factory
from core.models import GovernanceFinding, RecommendationRecord
from services import demo, governance_engine
from services.recommendations import providers

ENDPOINTS = ("/api/demo/governance/summary", "/api/demo/governance/findings",
             "/api/demo/ai/recommendations", "/api/demo/ai/status")


@pytest.fixture
def no_aws(monkeypatch):
    def boom(refresh):
        raise AssertionError("the demo must not read AWS")
    for name in ("_s3_source", "_ec2_source", "_rds_source", "_cost_source"):
        monkeypatch.setattr(governance_engine, name, boom)

    def no_llm(*args, **kwargs):
        raise AssertionError("the demo must not call an AI provider")
    monkeypatch.setattr(providers, "complete", no_llm)
    monkeypatch.setenv("CLOUDOPS_AI_PROVIDER", "ollama")


@pytest.mark.parametrize("path", ENDPOINTS)
def test_demo_is_public_labelled_and_cacheable(no_aws, path):
    response = TestClient(main.app).get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["demo"] is True and "Sample data" in body["sample_data_notice"]
    assert response.headers["cache-control"] == "public, max-age=300"


def test_demo_has_realistic_findings_and_recommendations(no_aws):
    client = TestClient(main.app)
    summary = client.get("/api/demo/governance/summary").json()
    assert summary["total_findings"] >= 15 and summary["by_severity"]["CRITICAL"] >= 2
    assert summary["scanned_at"] == demo.SCANNED_AT
    recs = client.get("/api/demo/ai/recommendations").json()
    assert recs["total"] == summary["total_findings"]
    assert all(r["generator"] == "rules" for r in recs["recommendations"])
    assert any(r["fix"] for r in recs["recommendations"]) and recs["plan"]["groups"]


def test_demo_findings_filters_and_validation(no_aws):
    client = TestClient(main.app)
    body = client.get("/api/demo/governance/findings", params={"category": "security"}).json()
    assert body["total"] > 0 and all(f["category"] == "SECURITY" for f in body["findings"])
    assert client.get("/api/demo/governance/findings", params={"severity": "nope"}).status_code == 422


def test_demo_writes_nothing(no_aws):
    client = TestClient(main.app)
    for path in ENDPOINTS:
        client.get(path)
    db = session_factory()()
    try:
        assert db.query(GovernanceFinding).count() == 0
        assert db.query(RecommendationRecord).count() == 0
    finally:
        db.close()


def test_demo_has_no_write_endpoints():
    client = TestClient(main.app)
    assert client.post("/api/demo/ai/analyze", json={}).status_code in (404, 405)
    assert client.patch("/api/demo/governance/findings/x", json={"status": "open"}).status_code in (404, 405)


def test_demo_can_be_turned_off(no_aws, monkeypatch):
    monkeypatch.setenv("CLOUDOPS_DEMO_ENABLED", "false")
    for path in ENDPOINTS:
        assert TestClient(main.app).get(path).status_code == 404


def test_real_endpoints_stay_private():
    client = TestClient(main.app)
    assert client.get("/api/governance/summary").status_code == 401
    assert client.get("/api/ai/recommendations").status_code == 401


def test_demo_copies_are_independent():
    first = demo.scan()
    first["findings"][0]["title"] = "changed"
    assert demo.scan()["findings"][0]["title"] != "changed"
