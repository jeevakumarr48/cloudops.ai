"""Grounding validator for generated recommendation text.

Rejects output that:

1. cites no evidence, or cites evidence ids that are not in the bundle;
2. mentions AWS resource identifiers or ARNs that are not in the evidence;
3. states figures (money, percentages, sizes, durations, decimals) that are
   not in the evidence;
4. claims or promises savings, or uses "guaranteed" language;
5. makes security claims when no security finding exists for the resource,
   or asserts a breach/compromise on any resource (never verifiable here);
6. proposes destructive or changing actions as automatic or unapproved;
7. contradicts the finding (e.g. "safe to ignore" on a confirmed finding,
   "confirmed" on an insufficient-evidence finding, "low risk" on a high one).

Any violation means the LLM text is discarded and the template is used.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

_SENTENCE_RE = re.compile(r"(?<=[.!?;])\s+|\n+")

_AWS_ID_RE = re.compile(
    r"\b(?:i|sg|vol|snap|ami|vpc|subnet|eni|rtb|igw|nat|eipalloc|db|acl|pcx|tgw|lt|elb)-[0-9a-z]{6,17}\b",
    re.IGNORECASE,
)
_ARN_RE = re.compile(r"\barn:aws[a-z-]*:[^\s\"'),]+", re.IGNORECASE)

_NUM = r"\d[\d,]*(?:\.\d+)?"
_FIGURE_RES = [
    re.compile(r"(?:\$|usd\s?|us\$)\s?(%s)" % _NUM, re.IGNORECASE),
    re.compile(r"(%s)\s?(?:%%|percent\b|usd\b|dollars?\b)" % _NUM, re.IGNORECASE),
    re.compile(r"(%s)\s?(?:[kmgtp]i?b|bytes?|iops|ms|milliseconds?|seconds?|minutes?|hours?|hrs?|days?|weeks?|months?"
               r"|years?|vcpus?|cpus?|instances?|x)\b" % _NUM, re.IGNORECASE),
    re.compile(r"\b(\d+\.\d+)\b"),
]

_SAVINGS_RE = re.compile(r"\b(?:sav(?:e|es|ed|ing|ings))\b", re.IGNORECASE)
_MONEY_RE = re.compile(r"(?:\$|\busd\b|\bdollars?\b|\d\s?%|\bpercent\b)", re.IGNORECASE)
_GUARANTEE_RE = re.compile(r"\b(?:guarantee[sd]?|guaranteeing|definitely (?:save|reduce|cut|lower))\b", re.IGNORECASE)

_SECURITY_RE = re.compile(
    r"\b(?:breach(?:es|ed)?|compromis\w*|exploit\w*|vulnerab\w*|attack(?:s|er|ers|ed)?|malware|ransomware|"
    r"exfiltrat\w*|intrusion|hack(?:ed|er|ers)?|leak(?:ed|s|ing)?|publicly (?:accessible|exposed|readable|reachable)|"
    r"exposed to the internet|open to the internet)\b",
    re.IGNORECASE,
)
_ASSERTED_INCIDENT_RE = re.compile(
    r"\b(?:has|have|had) been (?:breached|compromised|exploited|hacked|leaked|accessed by (?:an )?attackers?)\b|"
    r"\b(?:was|were|is|are) (?:being )?(?:breached|compromised|exploited|hacked|leaked)\b|"
    r"\battackers? (?:have|has|already) (?:accessed|exploited|compromised)\b",
    re.IGNORECASE,
)

_DESTRUCTIVE_RE = re.compile(
    r"\b(?:delet\w*|terminat\w*|drop\w*|remov\w*|destroy\w*|stop\w*|resiz\w*|downsiz\w*|modif\w*|disabl\w*|"
    r"purg\w*|wip\w*|shut\w* down|detach\w*|revok\w*|chang\w*|apply|applies|replac\w*|restor\w*)\b",
    re.IGNORECASE,
)
_UNAPPROVED_RE = re.compile(
    r"\b(?:automatic(?:ally)?|auto-?(?:delete|remediate|fix|apply)|without (?:approval|review|confirmation|asking|checking)|"
    r"no (?:need|approval|review) (?:to|is|needed|required)|cloudops(?: ai)? will)\b",
    re.IGNORECASE,
)

_DISMISSIVE_RE = re.compile(
    r"\b(?:safe to ignore|can (?:safely )?be ignored|ignore (?:this|it)|no (?:action|issue|problem|risk|concern)s? "
    r"(?:is |are )?(?:needed|required|here|present)?|not (?:an? )?(?:issue|problem|risk|concern)|nothing to (?:do|fix|worry)|"
    r"(?:is|are) (?:already )?(?:fine|secure|compliant|safe))\b",
    re.IGNORECASE,
)
_CERTAINTY_RE = re.compile(r"\b(?:confirmed|definitely|certainly|proven|clearly shows)\b", re.IGNORECASE)
_DOWNPLAY_RE = re.compile(r"\b(?:low (?:risk|priority|severity|impact)|minor|negligible|trivial|cosmetic)\b", re.IGNORECASE)


def _norm(value: str) -> str:
    value = value.replace(",", "")
    try:
        number = float(value)
    except ValueError:
        return value
    return ("%f" % number).rstrip("0").rstrip(".")


def _sentences(texts: Iterable[str]) -> List[str]:
    out: List[str] = []
    for text in texts:
        out.extend(s for s in _SENTENCE_RE.split(text or "") if s.strip())
    return out


def _texts(rewrite: Dict[str, Any]) -> List[str]:
    texts = [rewrite.get(k) or "" for k in ("problem", "why_it_matters", "suggested_action", "correlation_note")]
    texts += list(rewrite.get("expected_benefits") or []) + list(rewrite.get("potential_risks") or [])
    return [t for t in texts if isinstance(t, str)]


def validate(rewrite: Dict[str, Any], bundle: Dict[str, Any], check_citations: bool = True) -> List[str]:
    """Return a list of violations (empty when the text is acceptable)."""
    violations: List[str] = []
    finding = bundle["finding"]
    texts = _texts(rewrite)
    joined = "\n".join(texts)
    allowed_text = (bundle["allowed_text"] + " " + bundle["resource"]["id"]).lower()
    allowed_numbers = {_norm(n) for n in bundle["allowed_numbers"]}

    # 1. Citations.
    if check_citations:
        own = {e["id"] for e in bundle["evidence"]}
        known = own | {e["evidence_id"] for e in bundle["related_evidence"]}
        cited = list(rewrite.get("cited_evidence_ids") or [])
        unknown = sorted({c for c in cited if c not in known})
        if unknown:
            violations.append("cites unknown evidence ids: %s" % ", ".join(unknown[:5]))
        if not any(c in own for c in cited):
            violations.append("does not cite any evidence from this finding")

    # 2. Resource identifiers.
    for match in set(_AWS_ID_RE.findall(joined)) | set(_ARN_RE.findall(joined)):
        if match.lower().rstrip(".") not in allowed_text:
            violations.append("mentions a resource not in the evidence: %s" % match[:80])

    # 3. Figures.
    for pattern in _FIGURE_RES:
        for raw in pattern.findall(joined):
            if _norm(raw) not in allowed_numbers:
                violations.append("states a figure not in the evidence: %s" % raw)
    violations = list(dict.fromkeys(violations))

    sentences = _sentences(texts)
    # 4. Savings claims.
    if _GUARANTEE_RE.search(joined):
        violations.append("uses guaranteed-outcome language")
    for sentence in sentences:
        if _SAVINGS_RE.search(sentence) and (_MONEY_RE.search(sentence) or re.search(r"\d", sentence)):
            violations.append("claims a specific saving")
            break

    # 5. Security claims.
    if _ASSERTED_INCIDENT_RE.search(joined):
        violations.append("asserts a security incident that the evidence cannot show")
    if not bundle["has_security_finding"]:
        match = _SECURITY_RE.search(joined)
        if match:
            violations.append("makes a security claim (%s) without a security finding" % match.group(0))

    # 6. Unapproved destructive actions.
    for sentence in sentences:
        if _DESTRUCTIVE_RE.search(sentence) and _UNAPPROVED_RE.search(sentence):
            violations.append("proposes an automatic or unapproved change")
            break

    # 7. Contradictions.
    state = finding["evidence_state"]
    if state in ("CONFIRMED", "POTENTIAL") and _DISMISSIVE_RE.search(joined):
        violations.append("dismisses a %s finding" % state.lower())
    if state == "INSUFFICIENT_EVIDENCE" and _CERTAINTY_RE.search(joined):
        violations.append("states certainty on an insufficient-evidence finding")
    if finding["severity"] in ("CRITICAL", "HIGH") and _DOWNPLAY_RE.search(joined):
        violations.append("downplays a %s severity finding" % finding["severity"].lower())
    return violations
