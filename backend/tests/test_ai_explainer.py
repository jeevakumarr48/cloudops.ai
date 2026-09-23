"""Unit tests for the AI explainer fallback (no network, no API key)."""

from services.ai_explainer import build_fallback_explanation, explain_findings


SAMPLE_FINDING = {
    "resource_id": "i-123",
    "resource_type": "EC2",
    "severity": "medium",
    "issue": "Potential EC2 underutilization",
    "recommendation": "Review instance sizing before making an infrastructure change.",
    "estimated_monthly_savings": "Requires cost calculation",
    "tags": {},
    "evidence": ["Average CPUUtilization over the metric window is 8.4%."],
}


def test_fallback_includes_evidence():
    result = build_fallback_explanation([SAMPLE_FINDING])
    assert result["source"] == "deterministic"
    assert len(result["findings"]) == 1
    assert "8.4" in result["findings"][0]["explanation"]
    assert result["findings"][0]["recommended_action"] == SAMPLE_FINDING["recommendation"]
    assert result["findings"][0]["risk"] == "Medium"


def test_fallback_handles_no_findings():
    result = build_fallback_explanation([])
    assert result["findings"] == []
    assert "No findings" in result["summary"]


def test_explain_findings_uses_deterministic_fallback_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDOPS_AI_API_KEY", raising=False)
    result = explain_findings([SAMPLE_FINDING])
    assert result["source"] == "deterministic"
    assert result["findings"][0]["severity"] == "medium"
