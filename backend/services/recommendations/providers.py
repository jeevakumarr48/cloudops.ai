"""Optional LLM providers for rewriting template recommendations.

The LLM never decides anything. It receives one evidence bundle and may only
return the prose fields of ``LLMRewrite``; severity, evidence state, scores,
savings, confidence and the resource all stay with the rule engine. Every
response is validated before use (see ``validator``).

Configuration (environment only; nothing is required):

    CLOUDOPS_AI_PROVIDER   none (default) | ollama | openai_compatible
    CLOUDOPS_AI_MODEL      model name (ollama default: llama3.2:3b)
    CLOUDOPS_AI_BASE_URL   OpenAI-compatible base URL
                           (ollama default: http://localhost:11434/v1)
    CLOUDOPS_AI_API_KEY    only for openai_compatible (OPENAI_API_KEY also accepted)

For backward compatibility with the existing explainer, a configured
CLOUDOPS_AI_API_KEY with no provider set selects ``openai_compatible``.
Ollama only works where the API runs next to it (local development); a
Vercel function cannot reach a laptop's localhost.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

PROVIDERS = ("none", "ollama", "openai_compatible")

SYSTEM_PROMPT = (
    "You rewrite one cloud governance recommendation so an engineer can act on it. "
    "Rules: use ONLY facts in the evidence you are given. Do not invent resources, "
    "metrics, prices, costs, savings, percentages, dates or durations; only repeat "
    "numbers that appear in the evidence. Do not claim the resource was breached, "
    "compromised or exploited. Do not say anything is safe to ignore. Never suggest "
    "an automatic change: every action needs human review and approval. "
    "Cite the evidence ids you relied on. Respond with one JSON object only, with "
    "keys: problem (string), why_it_matters (string), suggested_action (string), "
    "expected_benefits (list of strings), potential_risks (list of strings), "
    "correlation_note (string or null), cited_evidence_ids (list of strings)."
)


class ProviderError(Exception):
    """The provider could not produce a usable response."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    base_url: str
    api_key: Optional[str]

    def public(self) -> Dict[str, Any]:
        """Safe to return to clients: never includes the key."""
        return {"provider": self.name, "model": self.model,
                "local": self.name == "ollama", "api_key_configured": bool(self.api_key)}


def _http_url(value: str) -> str:
    """Only http(s) endpoints: refuses file:, ftp: and other schemes urlopen accepts."""
    if urllib.parse.urlsplit(value).scheme not in ("http", "https"):
        raise ProviderError("CLOUDOPS_AI_BASE_URL must be an http or https URL.")
    return value


def config() -> Optional[ProviderConfig]:
    name = (os.environ.get("CLOUDOPS_AI_PROVIDER") or "").strip().lower()
    api_key = os.environ.get("CLOUDOPS_AI_API_KEY") or os.environ.get("OPENAI_API_KEY") or None
    if not name:
        name = "openai_compatible" if api_key else "none"
    if name not in PROVIDERS or name == "none":
        return None
    if name == "ollama":
        return ProviderConfig(
            name="ollama",
            model=os.environ.get("CLOUDOPS_AI_MODEL") or "llama3.2:3b",
            base_url=os.environ.get("CLOUDOPS_AI_BASE_URL") or "http://localhost:11434/v1",
            api_key=None,
        )
    if not api_key:
        return None
    return ProviderConfig(
        name="openai_compatible",
        model=os.environ.get("CLOUDOPS_AI_MODEL") or "gpt-4o-mini",
        base_url=os.environ.get("CLOUDOPS_AI_BASE_URL") or "https://api.openai.com/v1",
        api_key=api_key,
    )


def prompt_payload(bundle: Dict[str, Any], template: Dict[str, Any]) -> Dict[str, Any]:
    """What the model sees: facts and the draft, nothing else."""
    finding = bundle["finding"]
    return {
        "finding": {k: finding.get(k) for k in ("rule_id", "title", "description", "severity", "category",
                                                "evidence_state", "missing_information")},
        "resource": bundle["resource"],
        "evidence": [{"evidence_id": e["id"], "source": e["source"], "observation": e["observation"]}
                     for e in bundle["evidence"]],
        "related_findings": bundle["related"],
        "related_evidence": [{"evidence_id": e["evidence_id"], "observation": e["observation"]}
                             for e in bundle["related_evidence"]],
        "draft": {k: template[k] for k in ("problem", "why_it_matters", "suggested_action",
                                           "expected_benefits", "potential_risks", "correlation_note")},
    }


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse(content: str) -> Dict[str, Any]:
    text = _FENCE_RE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ProviderError("The model did not return a JSON object.")
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError as error:
        raise ProviderError("The model returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise ProviderError("The model did not return a JSON object.")
    return value


def _http_request(request: urllib.request.Request) -> urllib.request.Request:
    _http_url(request.full_url)
    return request


def complete(cfg: ProviderConfig, payload: Dict[str, Any], timeout: float = 25.0) -> Dict[str, Any]:
    """One chat completion. Raises ``ProviderError``; never logs the key."""
    body = json.dumps({
        "model": cfg.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = "Bearer %s" % cfg.api_key
    request = urllib.request.Request(cfg.base_url.rstrip("/") + "/chat/completions",  # noqa: S310 - scheme checked
                                     data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(_http_request(request), timeout=timeout) as response:  # noqa: S310 - scheme checked
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as error:
        raise ProviderError("The AI provider returned HTTP %d." % error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError("The AI provider could not be reached.") from None
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProviderError("The AI provider returned an unexpected response.") from None
    if not isinstance(content, str):
        raise ProviderError("The AI provider returned an unexpected response.")
    return _parse(content)
