"""AI explanation layer for CloudOps AI.

Flow::

    Decision Engine -> structured findings -> AI Explainer -> explanation

The explainer receives structured findings only. It never inspects AWS
credentials, never calls AWS, and never performs actions. If no AI API key is
configured, a deterministic fallback explanation is returned, so the platform
always has a useful result. Metrics and costs are only ever repeated from the
findings; nothing is fabricated.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

__all__ = ["explain_findings", "build_fallback_explanation"]

_RISK_BY_SEVERITY = {"high": "High", "medium": "Medium", "low": "Low"}

_SYSTEM_PROMPT = (
    "You are CloudOps AI, an advisory assistant for cloud infrastructure. "
    "You explain deterministic findings produced by a rule engine. Use ONLY "
    "the evidence provided; never invent AWS metrics, costs, resources, or "
    "savings. Never recommend deleting or stopping resources automatically. "
    "Always require human review. Respond with JSON only, using the shape "
    '{"summary": string, "findings": [{"issue": string, "severity": string, '
    '"evidence": [string], "explanation": string, "recommended_action": string, '
    '"risk": string}]}.'
)


def _risk_for(severity: Optional[str]) -> str:
    return _RISK_BY_SEVERITY.get((severity or "").strip().lower(), "Unknown")


def _fallback_finding(finding: Dict) -> Dict:
    issue = finding.get("issue") or "Finding"
    severity = finding.get("severity") or "unknown"
    evidence = [str(item) for item in (finding.get("evidence") or [])]
    evidence_sentence = " ".join(evidence) if evidence else "No additional evidence was available."
    return {
        "issue": issue,
        "severity": severity,
        "evidence": evidence,
        "explanation": "%s %s" % (issue, evidence_sentence),
        "recommended_action": finding.get("recommendation")
        or "Review this finding before making any change.",
        "risk": _risk_for(severity),
    }


def build_fallback_explanation(findings: Optional[List[Dict]]) -> Dict:
    """Return a deterministic, evidence-based explanation without any LLM."""
    findings = list(findings or [])
    if not findings:
        summary = "No findings were produced from the available data."
    else:
        counts = {"high": 0, "medium": 0, "low": 0}
        for finding in findings:
            key = (finding.get("severity") or "").strip().lower()
            if key in counts:
                counts[key] += 1
        summary = (
            "%d finding(s) detected: %d high, %d medium, %d low. "
            "Each finding is advisory and requires human review before any change."
            % (len(findings), counts["high"], counts["medium"], counts["low"])
        )
    return {
        "summary": summary,
        "findings": [_fallback_finding(finding) for finding in findings],
        "source": "deterministic",
    }


def _provider_config() -> Optional[Dict[str, str]]:
    """Read LLM provider configuration from environment variables only."""
    api_key = os.environ.get("CLOUDOPS_AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "base_url": os.environ.get("CLOUDOPS_AI_BASE_URL", "https://api.openai.com/v1"),
        "model": os.environ.get("CLOUDOPS_AI_MODEL", "gpt-4o-mini"),
    }


def _call_llm(config: Dict[str, str], findings: List[Dict]) -> Dict:
    """Call an OpenAI-compatible chat completions endpoint. Raises on error."""
    payload = json.dumps(
        {
            "model": config["model"],
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"findings": findings})},
            ],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        config["base_url"].rstrip("/") + "/chat/completions",
        data=payload,
        headers={
            "Authorization": "Bearer %s" % config["api_key"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        body = json.loads(response.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    return json.loads(content)


def _normalize_llm_result(result: Dict, findings: List[Dict]) -> Dict:
    """Validate the LLM response and guarantee the expected shape."""
    normalized_findings: List[Dict] = []
    raw_findings = result.get("findings") if isinstance(result, dict) else None
    source = findings
    for index, finding in enumerate(raw_findings or []):
        base = source[index] if index < len(source) else {}
        normalized_findings.append(
            {
                "issue": finding.get("issue") or base.get("issue") or "Finding",
                "severity": finding.get("severity") or base.get("severity") or "unknown",
                "evidence": finding.get("evidence") or base.get("evidence") or [],
                "explanation": finding.get("explanation")
                or _fallback_finding(base)["explanation"],
                "recommended_action": finding.get("recommended_action")
                or base.get("recommendation")
                or "Review this finding before making any change.",
                "risk": finding.get("risk") or _risk_for(base.get("severity")),
            }
        )
    if not normalized_findings:
        return build_fallback_explanation(findings)
    return {
        "summary": result.get("summary") or build_fallback_explanation(findings)["summary"],
        "findings": normalized_findings,
        "source": "llm",
    }


def explain_findings(findings: Optional[List[Dict]]) -> Dict:
    """Explain structured findings in human-readable form.

    Uses an LLM when configured via environment variables; otherwise returns
    a deterministic fallback. Never raises: on any provider error the
    fallback explanation is returned instead.
    """
    findings = list(findings or [])
    config = _provider_config()
    if not config:
        return build_fallback_explanation(findings)
    try:
        result = _call_llm(config, findings)
        return _normalize_llm_result(result, findings)
    except (urllib.error.URLError, KeyError, ValueError, TypeError, json.JSONDecodeError):
        fallback = build_fallback_explanation(findings)
        fallback["source"] = "deterministic_fallback"
        return fallback
