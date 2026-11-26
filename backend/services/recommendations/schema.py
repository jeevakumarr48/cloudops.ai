"""Pydantic schema for recommendations (the 12 required fields + tracing)."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ResourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    id: str
    region: Optional[str] = None


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    source: str
    observation: str


class Savings(BaseModel):
    """Savings are only ever stated when validated from measured data."""
    model_config = ConfigDict(extra="forbid")
    validated: bool = False
    amount_usd_per_month: Optional[float] = None
    basis: str = "Not estimated: no measured cost figure is available for this resource."


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str
    finding_id: str
    rule_id: str
    # 1-12: the required fields.
    title: str = Field(min_length=3, max_length=160)
    resource: ResourceRef
    problem: str = Field(min_length=10, max_length=1200)
    evidence: List[EvidenceRef] = Field(min_length=1)
    why_it_matters: str = Field(min_length=10, max_length=1200)
    suggested_action: str = Field(min_length=5, max_length=1200)
    expected_benefits: List[str] = Field(min_length=1, max_length=6)
    potential_risks: List[str] = Field(min_length=1, max_length=6)
    estimated_savings: Savings
    confidence: Literal["high", "medium", "low"]
    missing_information: List[str] = Field(default_factory=list, max_length=8)
    requires_human_approval: Literal[True] = True
    # Context and tracing.
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    category: str
    evidence_state: Literal["CONFIRMED", "POTENTIAL", "INSUFFICIENT_EVIDENCE"]
    priority_score: float
    remediation_steps: List[str] = Field(default_factory=list, max_length=10)
    related_findings: List[str] = Field(default_factory=list)
    correlation_note: Optional[str] = Field(default=None, max_length=800)
    generator: Literal["rules", "llm"]
    evidence_hash: str
    validation: dict = Field(default_factory=dict)


class LLMRewrite(BaseModel):
    """The only fields an LLM may return. Everything else comes from rules."""
    model_config = ConfigDict(extra="ignore")
    problem: str = Field(min_length=10, max_length=1200)
    why_it_matters: str = Field(min_length=10, max_length=1200)
    suggested_action: str = Field(min_length=5, max_length=1200)
    expected_benefits: List[str] = Field(min_length=1, max_length=6)
    potential_risks: List[str] = Field(min_length=1, max_length=6)
    correlation_note: Optional[str] = Field(default=None, max_length=800)
    cited_evidence_ids: List[str] = Field(min_length=1)
