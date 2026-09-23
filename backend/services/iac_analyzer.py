"""Terraform plan JSON and Infracost analysis for CloudOps AI.

This module is read-only with respect to infrastructure: it parses plan
artifacts and normalizes Infracost reports. It never runs ``terraform
apply`` or ``terraform plan`` and never modifies infrastructure.

Expected Terraform workflow (run by the user, not this service)::

    terraform plan -out tfplan
    terraform show -json tfplan > plan.json
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "IaCPlanError",
    "load_infracost_file",
    "load_plan_file",
    "normalize_infracost",
    "parse_plan",
    "infracost_status",
]


class IaCPlanError(RuntimeError):
    """Raised when a Terraform plan cannot be read or parsed."""


def _normalize_actions(actions: Optional[List[str]]) -> List[str]:
    """Collapse Terraform's delete+create action pair into ``replace``."""
    if not actions:
        return []
    if set(actions) == {"create", "delete"} and len(actions) == 2:
        return ["replace"]
    return list(actions)


def parse_plan(plan: Dict) -> Dict:
    """Normalize a decoded Terraform plan JSON document.

    Returns ``{"changes": [...]}`` where each change carries ``address``,
    ``resource_type``, ``name``, ``actions``, ``before`` and ``after``.
    """
    if not isinstance(plan, dict):
        raise IaCPlanError("Terraform plan must be a JSON object.")

    changes: List[Dict] = []
    for resource_change in plan.get("resource_changes") or []:
        if not isinstance(resource_change, dict):
            continue
        change = resource_change.get("change") or {}
        changes.append(
            {
                "address": resource_change.get("address"),
                "resource_type": resource_change.get("type"),
                "name": resource_change.get("name"),
                "actions": _normalize_actions(change.get("actions")),
                "before": change.get("before"),
                "after": change.get("after"),
            }
        )
    return {"changes": changes}


def load_plan_file(path: str) -> Dict:
    """Read and normalize a Terraform plan JSON file from disk."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as error:
        raise IaCPlanError("Terraform plan file not found: %s" % path) from error
    except json.JSONDecodeError as error:
        raise IaCPlanError("Invalid Terraform plan JSON: %s" % error) from error
    return parse_plan(data)


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_value(mapping: Dict, *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _as_list(value: Any) -> List:
    return value if isinstance(value, list) else []


def _resource_tags(value: Any) -> Dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {
            item.get("key") or item.get("Key"): item.get("value") or item.get("Value")
            for item in value
            if isinstance(item, dict) and (item.get("key") or item.get("Key"))
        }
    return {}


def _resource_address(resource: Dict) -> Optional[str]:
    value = _first_value(resource, "address", "resource_address", "name")
    return str(value) if value is not None else None


def _resource_type(resource: Dict) -> Optional[str]:
    value = _first_value(resource, "resource_type", "resourceType", "type")
    return str(value) if value is not None else None


def _resource_monthly_cost(resource: Dict) -> Optional[float]:
    """Read a resource total, falling back to its component totals."""
    resource_total = _to_float(_first_value(
        resource, "total_monthly_cost", "totalMonthlyCost", "monthly_cost", "monthlyCost"
    ))
    if resource_total is not None:
        return resource_total

    component_totals = []
    for component in _as_list(_first_value(resource, "cost_components", "costComponents")):
        if not isinstance(component, dict):
            continue
        total = _to_float(_first_value(component, "total_monthly_cost", "totalMonthlyCost"))
        if total is not None:
            component_totals.append(total)
    return sum(component_totals) if component_totals else None


def _resource_records(report: Dict) -> Iterable[Dict]:
    """Yield resources from scan reports and breakdown reports."""
    seen = set()

    def visit(resources: Any):
        for resource in _as_list(resources):
            if not isinstance(resource, dict):
                continue
            address = _resource_address(resource)
            marker = address if address else id(resource)
            if marker in seen:
                continue
            seen.add(marker)
            yield resource

    yield from visit(report.get("resources"))
    for project in _as_list(report.get("projects")):
        if not isinstance(project, dict):
            continue
        yield from visit(project.get("resources"))
        breakdown = project.get("breakdown")
        if isinstance(breakdown, dict):
            yield from visit(breakdown.get("resources"))

    finding_resources = {}
    for item in _as_list(report.get("failing_tagging")):
        if isinstance(item, dict) and item.get("address"):
            finding_resources[item["address"]] = {
                "address": item["address"],
                "resource_type": item.get("resource_type"),
            }
    for policy in _as_list(report.get("failing_policy_list")):
        if not isinstance(policy, dict):
            continue
        nested = policy.get("failing_finops") or policy.get("failing_policy") or policy.get("failing_tagging") or []
        for item in nested:
            if isinstance(item, dict) and item.get("address"):
                finding_resources[item["address"]] = {
                    "address": item["address"],
                    "resource_type": item.get("resource_type"),
                }
            for issue in item.get("issues", []) if isinstance(item, dict) else []:
                if isinstance(issue, dict) and issue.get("address"):
                    finding_resources[issue["address"]] = {
                        "address": issue["address"],
                        "resource_type": item.get("resource_type"),
                    }
    yield from visit(list(finding_resources.values()))


def _matching_findings(report: Dict, resource: Dict, kind: str) -> List[Dict]:
    address = _resource_address(resource)
    findings = [
        item
        for item in _as_list(
            resource.get(kind) or resource.get("taggingFindings" if kind == "tagging_findings" else "policyFindings")
        )
        if isinstance(item, dict)
    ]
    if kind == "tagging_findings":
        source = list(_as_list(report.get("failing_tagging")))
        source.extend(_as_list(report.get("tagging_findings")))
        for policy in _as_list(report.get("failing_policy_list")):
            if isinstance(policy, dict):
                source.extend(_as_list(policy.get("failing_tagging")))
        findings.extend(
            item for item in _as_list(source)
            if isinstance(item, dict) and (not address or item.get("address") == address)
        )
    else:
        for policy in _as_list(report.get("failing_policy_list")):
            if not isinstance(policy, dict):
                continue
            nested = policy.get("failing_finops") or policy.get("failing_policy") or []
            for item in nested:
                if not isinstance(item, dict):
                    continue
                if item.get("address") and (not address or item.get("address") == address):
                    findings.append({"policy": policy, "finding": item})
                for issue in item.get("issues", []):
                    if isinstance(issue, dict) and (not address or issue.get("address") == address):
                        findings.append({"policy": policy, "finding": issue})
    return findings


def _report_findings(report: Dict, kind: str) -> List[Dict]:
    findings = [item for item in _as_list(report.get(kind)) if isinstance(item, dict)]
    if kind == "tagging_findings":
        findings.extend(item for item in _as_list(report.get("failing_tagging")) if isinstance(item, dict))
        for policy in _as_list(report.get("failing_policy_list")):
            if isinstance(policy, dict):
                findings.extend(
                    item for item in _as_list(policy.get("failing_tagging"))
                    if isinstance(item, dict)
                )
    else:
        for policy in _as_list(report.get("failing_policy_list")):
            if not isinstance(policy, dict):
                continue
            nested = policy.get("failing_finops") or policy.get("failing_policy") or []
            for item in nested:
                if not isinstance(item, dict):
                    continue
                issues = item.get("issues") or [item]
                findings.extend(
                    {"policy": policy, "finding": issue}
                    for issue in issues
                    if isinstance(issue, dict)
                )
    return findings


def normalize_infracost(report: Any) -> Dict:
    """Normalize Infracost scan and breakdown reports into one safe shape.

    Returns a ``status`` of ``"ok"``, ``"not_configured"``, or ``"error"``.
    No cost values are invented; only values present in the report are used.
    """
    if not isinstance(report, dict):
        return {"status": "not_configured", "detail": "No Infracost report was provided."}

    currency = report.get("currency") or "USD"
    report_tagging_findings = _report_findings(report, "tagging_findings")
    report_policy_findings = _report_findings(report, "policy_findings")
    resources: List[Dict] = []
    for raw_resource in _resource_records(report):
        cost_components = _first_value(raw_resource, "cost_components", "costComponents") or []
        resources.append(
            {
                "address": _resource_address(raw_resource),
                "name": raw_resource.get("name"),
                "resource_type": _resource_type(raw_resource),
                "monthly_cost": _resource_monthly_cost(raw_resource),
                "base_monthly_cost": _to_float(_first_value(
                    raw_resource, "base_monthly_cost", "baseMonthlyCost"
                )),
                "usage_monthly_cost": _to_float(_first_value(
                    raw_resource, "usage_monthly_cost", "usageMonthlyCost"
                )),
                "cost_components": cost_components,
                "subresources": _as_list(raw_resource.get("subresources")),
                "is_supported": raw_resource.get("is_supported", raw_resource.get("isSupported")),
                "is_free": raw_resource.get("is_free", raw_resource.get("isFree")),
                "supports_tags": raw_resource.get("supports_tags", raw_resource.get("supportsTags")),
                "supports_default_tags": raw_resource.get(
                    "supports_default_tags", raw_resource.get("supportsDefaultTags")
                ),
                "tags": _resource_tags(raw_resource.get("tags")),
                "metadata": raw_resource.get("metadata") or {},
                "tagging_findings": _matching_findings(report, raw_resource, "tagging_findings"),
                "policy_findings": _matching_findings(report, raw_resource, "policy_findings"),
            }
        )

    # Infracost "diff" reports expose changes under a top-level "diff" object.
    diff = report.get("diff")
    if isinstance(diff, dict):
        currency = diff.get("currency") or currency
        change = _to_float(_first_value(diff, "monthly_cost_change", "totalMonthlyCost"))
        before = _to_float(_first_value(diff, "totalMonthlyCostBefore", "total_monthly_cost_before"))
        if change is None and before is None:
            if not resources:
                return {"status": "not_configured", "detail": "Infracost diff contained no cost data."}
        planned = None
        if before is not None and change is not None:
            planned = round(before + change, 2)
        return {
            "status": "ok",
            "current_monthly_cost": before,
            "planned_monthly_cost": planned,
            "monthly_cost_change": change,
            "currency": currency,
            "resources": resources,
            "tagging_findings": report_tagging_findings,
            "policy_findings": report_policy_findings,
        }

    total = _to_float(_first_value(report, "monthly_cost", "total_monthly_cost", "totalMonthlyCost"))
    if total is None and isinstance(report.get("summary"), dict):
        total = _to_float(_first_value(
            report["summary"], "monthly_cost", "total_monthly_cost", "totalMonthlyCost"
        ))
    if total is None and resources:
        known_costs = [item["monthly_cost"] for item in resources if item["monthly_cost"] is not None]
        total = round(sum(known_costs), 2) if known_costs else None
    if total is not None:
        return {
            "status": "ok",
            "current_monthly_cost": None,
            "planned_monthly_cost": total,
            "monthly_cost_change": None,
            "currency": currency,
            "resources": resources,
            "tagging_findings": report_tagging_findings,
            "policy_findings": report_policy_findings,
        }

    if resources:
        return {
            "status": "ok",
            "current_monthly_cost": None,
            "planned_monthly_cost": None,
            "monthly_cost_change": None,
            "currency": currency,
            "resources": resources,
            "tagging_findings": report_tagging_findings,
            "policy_findings": report_policy_findings,
        }

    return {"status": "not_configured", "detail": "Infracost report contained no cost data."}


def load_infracost_file(path: str) -> Dict:
    """Read an Infracost JSON file, returning a clean status on failure."""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"status": "not_configured", "detail": "Infracost report not found: %s" % path}
    except json.JSONDecodeError as error:
        return {"status": "error", "detail": "Invalid Infracost JSON: %s" % error}
    return normalize_infracost(data)


def infracost_status() -> Dict:
    """Report whether the optional Infracost integration is configured.

    Infracost is entirely optional; the presence of ``INFRACOST_API_KEY``
    (an environment variable) is the only signal checked. The key value is
    never read out, logged, or returned.
    """
    if os.environ.get("INFRACOST_API_KEY"):
        return {"status": "configured", "detail": "Infracost API key is configured."}
    return {
        "status": "not_configured",
        "detail": "INFRACOST_API_KEY is not set; Infracost integration is optional.",
    }
