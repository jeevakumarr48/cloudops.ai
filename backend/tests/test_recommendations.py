"""Phase 6: recommendation schema, templates, validator, providers, cache, endpoints."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
from core.models import AuditEvent, RecommendationFeedback, RecommendationRecord
from services import governance_engine
from services.governance_common import CONFIRMED, INSUFFICIENT_EVIDENCE, POTENTIAL, Evaluation
from services.recommendations import providers, service, templates, validator
from services.recommendations.context import build_bundles, evidence_hash
from services.recommendations.schema import Recommendation

PASSWORD = "correct horse battery"
REQUIRED = ("title", "resource", "problem", "evidence", "why_it_matters", "suggested_action", "expected_benefits",
            "potential_risks", "estimated_savings", "confidence", "missing_information", "requires_human_approval")
CATEGORY_BY_PREFIX = {"S3_PUBLIC_POLICY": "SECURITY", "S3_PUBLIC_ACL": "SECURITY", "S3_BLOCK_PUBLIC_ACCESS": "SECURITY",
                      "S3_DEFAULT_ENCRYPTION": "SECURITY", "RDS_PUBLIC_ACCESS": "SECURITY",
                      "RDS_STORAGE_ENCRYPTION": "SECURITY", "EC2_OPEN_ADMIN_PORTS": "SECURITY"}


def make(rule_id="S3_PUBLIC_POLICY", state=CONFIRMED, severity="CRITICAL", resource="bucket-a", rtype="S3",
         category="SECURITY", observations=("Bucket policy allows Principal * for s3:GetObject.",),
         description="The bucket policy makes objects publicly readable.", **extra):
    ev = Evaluation(rtype, resource, "us-east-1", rule_id, category, "Bucket policy grants public access", "test")
    for observation in observations:
        ev.cite("s3:GetBucketPolicyStatus", observation)
    result = ev.result(state, severity, description,
                       recommendation="Remove the public statement after confirming no consumer needs it.",
                       remediation_steps=["Review consumers.", "Edit the bucket policy."], confidence="high",
                       missing_information=[])
    result.update(extra)
    result["priority"] = governance_engine.score(result)
    result["lifecycle"] = {"status": "open"}
    return result


def bundle_for(finding, *others):
    return build_bundles([finding, *others])[0]


GOOD = {
    "problem": "The bucket policy on bucket-a allows Principal * to read objects, so anyone can download them.",
    "why_it_matters": "Anyone on the internet can copy the data in this bucket.",
    "suggested_action": "After the owner confirms no consumer needs public reads, remove the public statement.",
    "expected_benefits": ["Data is no longer readable by anyone."],
    "potential_risks": ["Public consumers of the bucket will lose access."],
    "correlation_note": None,
    "cited_evidence_ids": ["s3_public_policy-e1"],
}


# --- templates -------------------------------------------------------------------


def test_every_rule_has_template_text():
    assert set(governance_engine.RULE_META) <= set(templates.RULE_TEXT)


@pytest.mark.parametrize("rule_id", sorted(governance_engine.RULE_META))
def test_every_template_has_all_fields_and_passes_validator(rule_id):
    category = CATEGORY_BY_PREFIX.get(rule_id, "CONFIGURATION")
    finding = make(rule_id, POTENTIAL, "MEDIUM", category=category, observations=("Observed value 14 days.",),
                   description="The rule condition was observed on this resource.")
    bundle = bundle_for(finding)
    rec = templates.build(bundle)
    dumped = rec.model_dump()
    for field in REQUIRED:
        assert field in dumped
    assert rec.requires_human_approval is True
    assert rec.generator == "rules"
    assert rec.estimated_savings.validated is False and rec.estimated_savings.amount_usd_per_month is None
    assert validator.validate(dumped, bundle, check_citations=False) == []


def test_unknown_rule_uses_category_fallback():
    finding = make("IAC_OTHER", POTENTIAL, "LOW", resource="aws_instance.web", rtype="IAC", category="INFRASTRUCTURE")
    rec = templates.build(bundle_for(finding))
    assert rec.why_it_matters.startswith("This affects a proposed infrastructure change")


def test_savings_only_when_measured():
    finding = make(measured_savings_usd=12.5, savings_basis="Infracost monthly delta for this change.")
    rec = templates.build(bundle_for(finding))
    assert rec.estimated_savings.validated is True and rec.estimated_savings.amount_usd_per_month == 12.5
    no_basis = templates.build(bundle_for(make(measured_savings_usd=12.5)))
    assert no_basis.estimated_savings.validated is False


def test_insufficient_evidence_is_labelled():
    rec = templates.build(bundle_for(make("EC2_LOW_UTILIZATION", INSUFFICIENT_EVIDENCE, "LOW", "i-0abc12345",
                                          "EC2", "UTILIZATION")))
    assert rec.problem.startswith("Not enough evidence to decide.")


def test_correlation_between_findings_on_same_resource():
    public = make()
    unencrypted = make("S3_DEFAULT_ENCRYPTION", CONFIRMED, "MEDIUM")
    rec = templates.build(bundle_for(public, unencrypted))
    assert "unencrypted data" in rec.correlation_note
    assert rec.related_findings == [unencrypted["finding_id"]]


def test_schema_forbids_approval_false_and_extra_fields():
    rec = templates.build(bundle_for(make())).model_dump()
    with pytest.raises(ValidationError):
        Recommendation.model_validate(dict(rec, requires_human_approval=False))
    with pytest.raises(ValidationError):
        Recommendation.model_validate(dict(rec, auto_apply=True))
    with pytest.raises(ValidationError):
        Recommendation.model_validate(dict(rec, evidence=[]))


def test_evidence_hash_tracks_evidence_only():
    a = make()
    b = dict(a, priority={"score": 1.0}, lifecycle={"status": "acknowledged"})
    assert evidence_hash(a) == evidence_hash(b)
    c = make(observations=("Different observation.",))
    assert evidence_hash(a) != evidence_hash(c)


# --- validator -------------------------------------------------------------------


def test_grounded_rewrite_passes():
    assert validator.validate(GOOD, bundle_for(make())) == []


def test_numbers_from_evidence_are_allowed():
    finding = make("RDS_LOW_UTILIZATION", POTENTIAL, "LOW", "db-1", "RDS", "UTILIZATION",
                   observations=("Average CPU was 3.2% over 14 days.",))
    rewrite = dict(GOOD, problem="Average CPU stayed at 3.2% across 14 days of data.",
                   cited_evidence_ids=["rds_low_utilization-e1"])
    assert validator.validate(rewrite, bundle_for(finding)) == []


@pytest.mark.parametrize("change, expected", [
    ({"cited_evidence_ids": ["made-up-e9"]}, "cites unknown evidence ids"),
    ({"cited_evidence_ids": []}, "does not cite any evidence"),
    ({"problem": "Instance i-0deadbeef1234 also reads this bucket publicly."}, "mentions a resource not in the evidence"),
    ({"problem": "The role arn:aws:iam::123456789012:role/x can also read the bucket."}, "mentions a resource"),
    ({"why_it_matters": "This bucket costs $42 per month to serve publicly."}, "states a figure"),
    ({"why_it_matters": "About 30% of objects are downloaded by anonymous users."}, "states a figure"),
    ({"why_it_matters": "The bucket holds 500 GB of public data."}, "states a figure"),
    ({"expected_benefits": ["You could save on data transfer by closing it, maybe 10 dollars."]}, "claims a specific saving"),
    ({"expected_benefits": ["This is guaranteed to stop all unwanted access."]}, "guaranteed"),
    ({"problem": "The bucket has been compromised by attackers who copied the data."}, "asserts a security incident"),
    ({"suggested_action": "CloudOps AI will automatically delete the public statement."}, "automatic or unapproved"),
    ({"suggested_action": "Remove the policy statement without approval from the owner."}, "automatic or unapproved"),
    ({"why_it_matters": "This is safe to ignore for a test bucket."}, "dismisses a confirmed finding"),
    ({"why_it_matters": "This is a minor configuration detail."}, "downplays a critical severity finding"),
])
def test_validator_rejects(change, expected):
    violations = validator.validate(dict(GOOD, **change), bundle_for(make()))
    assert any(expected in v for v in violations), violations


def test_security_claim_without_security_finding_is_rejected():
    finding = make("S3_LIFECYCLE", POTENTIAL, "LOW", category="STORAGE", observations=("No lifecycle rules.",))
    rewrite = dict(GOOD, why_it_matters="Attackers can exploit buckets without lifecycle rules.",
                   cited_evidence_ids=["s3_lifecycle-e1"])
    assert any("security claim" in v for v in validator.validate(rewrite, bundle_for(finding)))


def test_certainty_on_insufficient_evidence_is_rejected():
    finding = make("EC2_LOW_UTILIZATION", INSUFFICIENT_EVIDENCE, "LOW", "i-0abc12345", "EC2", "UTILIZATION",
                   observations=("Only part of the window had data.",))
    rewrite = dict(GOOD, problem="The instance is confirmed to be oversized for its workload.",
                   cited_evidence_ids=["ec2_low_utilization-e1"])
    assert any("certainty" in v for v in validator.validate(rewrite, bundle_for(finding)))


# --- providers -------------------------------------------------------------------


def test_provider_defaults_to_none(monkeypatch):
    for key in ("CLOUDOPS_AI_PROVIDER", "CLOUDOPS_AI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert providers.config() is None


def test_provider_selection_and_key_never_public(monkeypatch):
    monkeypatch.delenv("CLOUDOPS_AI_PROVIDER", raising=False)
    monkeypatch.setenv("CLOUDOPS_AI_API_KEY", "sk-secret")
    cfg = providers.config()
    assert cfg.name == "openai_compatible"
    assert "sk-secret" not in str(cfg.public())
    monkeypatch.setenv("CLOUDOPS_AI_PROVIDER", "ollama")
    cfg = providers.config()
    assert cfg.name == "ollama" and cfg.base_url == "http://localhost:11434/v1" and cfg.api_key is None
    monkeypatch.setenv("CLOUDOPS_AI_PROVIDER", "none")
    assert providers.config() is None


def test_provider_response_parsing():
    assert providers._parse('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(providers.ProviderError):
        providers._parse("not json")


def test_prompt_contains_only_bundle_facts():
    finding = make()
    bundle = bundle_for(finding)
    payload = providers.prompt_payload(bundle, templates.build(bundle).model_dump(mode="json"))
    assert set(payload) == {"finding", "resource", "evidence", "related_findings", "related_evidence", "draft"}
    assert "priority" not in payload["finding"] and "estimated_savings" not in payload["draft"]


# --- service: cache, analyze, caps -------------------------------------------------


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_AI_PROVIDER", "ollama")
    state = {"calls": 0, "reply": dict(GOOD), "error": None}

    def complete(cfg, payload, timeout=25.0):
        state["calls"] += 1
        if state["error"]:
            raise providers.ProviderError(state["error"])
        reply = dict(state["reply"])
        reply["cited_evidence_ids"] = [payload["evidence"][0]["evidence_id"]] if reply["cited_evidence_ids"] else []
        return reply

    monkeypatch.setattr(providers, "complete", complete)
    return state


def db_session():
    from core.database import session_factory
    return session_factory()()


def test_list_never_calls_provider_and_persists_once(fake_llm):
    db = db_session()
    first = service.list_recommendations([make()], db, "global")
    second = service.list_recommendations([make()], db, "global")
    assert fake_llm["calls"] == 0
    assert first["persisted"] is True
    assert first["recommendations"][0]["recommendation_id"] == second["recommendations"][0]["recommendation_id"]
    assert db.query(RecommendationRecord).count() == 1
    db.close()


def test_list_works_without_database():
    result = service.list_recommendations([make()], None, "global")
    assert result["persisted"] is False and result["recommendations"][0]["generator"] == "rules"


def test_false_positives_are_excluded():
    finding = make()
    finding["lifecycle"] = {"status": "false_positive"}
    assert service.list_recommendations([finding], None, "global")["recommendations"] == []


def test_analyze_rewrites_then_reuses_cache(fake_llm):
    db = db_session()
    result = service.analyze([make()], db, "global")
    assert result["results"][0]["outcome"] == "rewritten" and fake_llm["calls"] == 1
    again = service.analyze([make()], db, "global")
    assert again["results"][0]["outcome"] == "cached" and fake_llm["calls"] == 1
    listed = service.list_recommendations([make()], db, "global")["recommendations"][0]
    assert listed["generator"] == "llm" and listed["validation"]["passed"] is True
    assert listed["severity"] == "CRITICAL" and listed["estimated_savings"]["validated"] is False
    db.close()


def test_new_evidence_invalidates_cache(fake_llm):
    db = db_session()
    service.analyze([make()], db, "global")
    service.analyze([make(observations=("Policy changed: now allows s3:PutObject too.",))], db, "global")
    assert fake_llm["calls"] == 2
    db.close()


def test_rejected_output_falls_back_and_is_not_retried(fake_llm):
    fake_llm["reply"] = dict(GOOD, why_it_matters="Closing it will save $300 every month.")
    db = db_session()
    result = service.analyze([make()], db, "global")["results"][0]
    assert result["outcome"] == "rejected" and result["generator"] == "rules"
    stored = service.list_recommendations([make()], db, "global")["recommendations"][0]
    assert stored["generator"] == "rules" and stored["validation"]["passed"] is False
    assert stored["validation"]["violations"]
    assert "$300" not in str(stored)
    assert service.analyze([make()], db, "global")["results"][0]["outcome"] == "previously_rejected"
    assert fake_llm["calls"] == 1
    db.close()


def test_schema_invalid_output_falls_back(fake_llm):
    fake_llm["reply"] = {"problem": "short", "cited_evidence_ids": ["x"]}
    db = db_session()
    result = service.analyze([make()], db, "global")["results"][0]
    assert result["outcome"] == "rejected" and "schema" in result["violations"][0]
    db.close()


def test_provider_error_falls_back_and_can_retry(fake_llm):
    fake_llm["error"] = "The AI provider could not be reached."
    db = db_session()
    assert service.analyze([make()], db, "global")["results"][0]["outcome"] == "provider_error"
    fake_llm["error"] = None
    assert service.analyze([make()], db, "global")["results"][0]["outcome"] == "rewritten"
    db.close()


def test_daily_call_cap(fake_llm, monkeypatch):
    monkeypatch.setenv("CLOUDOPS_AI_DAILY_CALL_LIMIT", "1")
    db = db_session()
    findings = [make(), make(resource="bucket-b")]
    outcomes = [r["outcome"] for r in service.analyze(findings, db, "global")["results"]]
    assert sorted(outcomes) == ["daily_limit_reached", "rewritten"] and fake_llm["calls"] == 1
    db.close()


def test_analyze_without_provider_makes_no_calls(monkeypatch):
    monkeypatch.delenv("CLOUDOPS_AI_PROVIDER", raising=False)
    monkeypatch.delenv("CLOUDOPS_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    db = db_session()
    result = service.analyze([make()], db, "global")
    assert result["provider_calls"] == 0 and result["results"][0]["outcome"] == "no_provider"
    db.close()


def test_analyze_limit_is_capped(fake_llm):
    db = db_session()
    findings = [make(resource="bucket-%d" % i) for i in range(15)]
    assert len(service.analyze(findings, db, "global", limit=50)["results"]) == service.MAX_ANALYZE
    db.close()


def test_posture_summary_is_counts_only():
    summary = service.posture_summary(service.list_recommendations([make()], None, "global")["recommendations"])
    assert "1 recommendation(s): 1 critical." in summary["text"]
    assert "require human approval" in summary["text"]


# --- endpoints -------------------------------------------------------------------


@pytest.fixture
def sources(monkeypatch):
    state = {"s3": [make()]}
    monkeypatch.setattr(governance_engine, "_s3_source", lambda refresh: [dict(f) for f in state["s3"]])
    monkeypatch.setattr(governance_engine, "_ec2_source", lambda refresh: [])
    monkeypatch.setattr(governance_engine, "_rds_source", lambda refresh: [])
    monkeypatch.setattr(governance_engine, "_cost_source", lambda refresh: [])
    return state


@pytest.fixture
def operator(monkeypatch, sources):
    monkeypatch.setenv("CLOUDOPS_COOKIE_SECURE", "false")
    monkeypatch.setenv("CLOUDOPS_OPERATOR_EMAILS", "ops@example.com")
    client = TestClient(main.app)
    client.post("/api/auth/register", json={"email": "ops@example.com", "password": PASSWORD})
    return client


def test_endpoints_are_private_by_default(sources):
    anon = TestClient(main.app)
    assert anon.get("/api/ai/recommendations").status_code == 401
    assert anon.get("/api/ai/status").status_code == 401
    assert anon.post("/api/ai/analyze", json={}).status_code == 401


def test_list_endpoint(operator, fake_llm):
    response = operator.get("/api/ai/recommendations")
    body = response.json()
    assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
    assert body["total"] == 1 and body["persisted"] is True
    rec = body["recommendations"][0]
    assert rec["requires_human_approval"] is True and rec["feedback"] is None
    assert fake_llm["calls"] == 0


def test_status_endpoint_hides_key(operator, monkeypatch):
    monkeypatch.setenv("CLOUDOPS_AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CLOUDOPS_AI_API_KEY", "sk-very-secret")
    body = operator.get("/api/ai/status").json()
    assert body["provider"]["provider"] == "openai_compatible" and body["provider"]["api_key_configured"] is True
    assert "sk-very-secret" not in str(body)


def test_analyze_endpoint(operator, fake_llm):
    assert operator.post("/api/ai/analyze", content="{}", headers={"content-type": "text/plain"}).status_code == 415
    assert operator.post("/api/ai/analyze", json={"limit": 50}).status_code == 422
    body = operator.post("/api/ai/analyze", json={"limit": 3}).json()
    assert body["provider_calls"] == 1 and body["results"][0]["outcome"] == "rewritten"
    assert body["daily_call_limit"] == 20 and body["calls_used_today"] == 1
    db = db_session()
    assert db.query(AuditEvent).filter_by(action="ai.analyze").count() == 1
    db.close()


def test_feedback_endpoint(operator):
    rid = operator.get("/api/ai/recommendations").json()["recommendations"][0]["recommendation_id"]
    url = "/api/ai/recommendations/%s/feedback" % rid
    response = operator.post(url, json={"decision": "remediation_in_progress", "note": "ticket OPS-1"})
    assert response.status_code == 200 and response.json()["changes_applied"] is False
    listed = operator.get("/api/ai/recommendations").json()["recommendations"][0]
    assert listed["feedback"]["decision"] == "remediation_in_progress"
    assert operator.post(url, json={"decision": "auto_fix"}).status_code == 422
    assert operator.post("/api/ai/recommendations/nope/feedback", json={"decision": "accepted"}).status_code == 404
    db = db_session()
    assert db.query(RecommendationFeedback).count() == 1
    assert db.query(AuditEvent).filter_by(action="recommendation.feedback").count() == 1
    db.close()


def test_writes_require_operator(operator):
    rid = operator.get("/api/ai/recommendations").json()["recommendations"][0]["recommendation_id"]
    other = TestClient(main.app)
    other.post("/api/auth/register", json={"email": "viewer@example.com", "password": PASSWORD})
    assert other.post("/api/ai/recommendations/%s/feedback" % rid, json={"decision": "accepted"}).status_code == 403
    assert other.post("/api/ai/analyze", json={}).status_code == 403
