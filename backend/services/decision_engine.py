"""Deterministic decision engine for CloudOps AI.

Rules detect findings; AI only explains them later. This module is pure: it
performs no AWS calls and never stops, starts, or deletes anything. It only
reads structured data that was already collected.

Findings are dictionaries containing at least::

    resource_id, resource_type, severity, issue, recommendation,
    estimated_monthly_savings, tags, evidence
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "INSTANCE_SIZE_ORDER",
    "MEANINGFUL_MONTHLY_COST",
    "UNDERUTILIZED_CPU_THRESHOLD",
    "analyze_ec2_resource",
    "analyze_ec2_resources",
    "analyze_iac_changes",
    "normalize_metrics",
]

# Rule thresholds (deterministic, documented).
UNDERUTILIZED_CPU_THRESHOLD = 15.0
MEANINGFUL_MONTHLY_COST = 20.0
PRODUCTION_TAG_VALUES = {"production", "prod"}

# Relative size ordering within an EC2 instance family. Used only to detect a
# proposed capacity increase in an IaC change.
INSTANCE_SIZE_ORDER: Dict[str, int] = {
    "nano": 1,
    "micro": 2,
    "small": 3,
    "medium": 4,
    "large": 5,
    "xlarge": 6,
    "2xlarge": 7,
    "4xlarge": 8,
    "6xlarge": 9,
    "8xlarge": 10,
    "9xlarge": 11,
    "10xlarge": 12,
    "12xlarge": 13,
    "16xlarge": 14,
    "18xlarge": 15,
    "24xlarge": 16,
    "32xlarge": 17,
    "metal": 18,
}


def _instance_id(instance: Dict) -> Optional[str]:
    return instance.get("InstanceId") or instance.get("instance_id")


def _state(instance: Dict) -> Optional[str]:
    state = instance.get("State")
    if isinstance(state, dict):
        return state.get("Name")
    return state or instance.get("state")


def _tags(instance: Dict) -> Dict[str, Any]:
    tags = instance.get("Tags") or instance.get("tags") or {}
    if isinstance(tags, list):
        return {
            tag.get("Key"): tag.get("Value")
            for tag in tags
            if isinstance(tag, dict) and tag.get("Key")
        }
    return dict(tags)


def _is_production(tags: Dict[str, Any]) -> bool:
    for key in ("Environment", "environment", "env"):
        value = tags.get(key)
        if value:
            return str(value).strip().lower() in PRODUCTION_TAG_VALUES
    return False


def _finding(
    resource_id: Optional[str],
    severity: str,
    issue: str,
    recommendation: str,
    evidence: List[str],
    tags: Dict[str, Any],
    estimated_monthly_savings: Any = 0,
    resource_type: str = "EC2",
) -> Dict:
    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "severity": severity,
        "issue": issue,
        "recommendation": recommendation,
        "estimated_monthly_savings": estimated_monthly_savings,
        "tags": tags,
        "evidence": evidence,
    }


_METRIC_ID_KEYS = ("resource_id", "address", "instance_id", "id")


def _metric_id(entry: Dict) -> Optional[str]:
    for key in _METRIC_ID_KEYS:
        value = entry.get(key)
        if value:
            return str(value)
    return None


def _normalize_metric_entry(entry: Dict) -> Dict:
    return {
        "instance_id": _metric_id(entry) or entry.get("instance_id"),
        "cpu_average": entry.get("cpu_average"),
        "cpu_max": entry.get("cpu_max", entry.get("cpu_peak")),
        "period_hours": entry.get("period_hours"),
        "data_points": entry.get("data_points", 0),
    }


def normalize_metrics(metrics: Any) -> Dict[str, Dict]:
    """Normalize metric records into a dict keyed by resource/instance id.

    Accepts every shape the API may receive, so downstream rule access is
    always ``metrics.get(id).get("cpu_average")`` on a real mapping:

    - ``None`` or empty -> ``{}``
    - a mapping already keyed by resource id
    - a list of records (as returned by ``/api/metrics/ec2``) that carry an id
      in ``resource_id``, ``address``, ``instance_id`` or ``id``

    Records without CPU data are preserved with ``cpu_average=None`` so the
    engine treats them as "no metric data" instead of crashing.
    """
    normalized: Dict[str, Dict] = {}
    if not metrics:
        return normalized

    if isinstance(metrics, dict):
        for key, value in metrics.items():
            if isinstance(value, dict):
                entry = _normalize_metric_entry(value)
                entry["instance_id"] = value.get("instance_id") or key
                normalized[str(key)] = entry
    elif isinstance(metrics, list):
        for item in metrics:
            if not isinstance(item, dict):
                continue
            key = _metric_id(item)
            if not key:
                continue
            normalized[key] = _normalize_metric_entry(item)

    return normalized


def analyze_ec2_resource(
    instance: Dict,
    metrics: Optional[Dict] = None,
    cost: Optional[Dict] = None,
) -> List[Dict]:
    """Return deterministic findings for a single EC2 instance.

    ``metrics`` is an optional ``{"cpu_average": float, "cpu_max": float,
    "period_hours": int, "data_points": int}`` mapping as produced by
    ``services.aws_metrics``. ``cost`` is an optional mapping with a reliable
    ``monthly_cost`` for this specific resource; if AWS cannot provide a
    reliable per-instance cost, it must be omitted rather than guessed.
    """
    findings: List[Dict] = []
    instance_id = _instance_id(instance)
    state = _state(instance)
    tags = _tags(instance)

    # Rule 1: stopped EC2 instance.
    if state == "stopped":
        findings.append(
            _finding(
                instance_id,
                "medium",
                "Stopped EC2 instance",
                "Review whether this instance is still required. "
                "EBS storage charges may still apply.",
                ["Instance state is 'stopped'."],
                tags,
                "Requires cost calculation",
            )
        )

    # Rule 2: missing Owner tag.
    if "Owner" not in tags:
        findings.append(
            _finding(
                instance_id,
                "low",
                "Missing Owner tag",
                "Add an Owner tag to improve resource accountability.",
                ["Instance has no 'Owner' tag."],
                tags,
                0,
            )
        )

    cpu_average = (metrics or {}).get("cpu_average")
    has_metrics = metrics is not None and cpu_average is not None
    low_cpu = bool(has_metrics and cpu_average < UNDERUTILIZED_CPU_THRESHOLD)

    # Rule 3: underutilized EC2 (only with real CloudWatch data).
    if low_cpu:
        evidence = [
            "Average CPUUtilization over the metric window is %s%%." % cpu_average
        ]
        if metrics.get("cpu_max") is not None:
            evidence.append("Peak CPUUtilization is %s%%." % metrics.get("cpu_max"))
        if metrics.get("period_hours") is not None:
            evidence.append(
                "Metric window is %s hours across %s datapoints."
                % (metrics.get("period_hours"), metrics.get("data_points", 0))
            )

        if _is_production(tags):
            evidence.append(
                "Resource is tagged as production, so this is a review item, "
                "not a shutdown candidate."
            )
            recommendation = (
                "Production resource: review instance sizing, scheduling, or "
                "workload requirements with the owning team before making any "
                "infrastructure change."
            )
        else:
            recommendation = (
                "Review instance sizing, scheduling, or workload requirements "
                "before making an infrastructure change."
            )

        findings.append(
            _finding(
                instance_id,
                "medium",
                "Potential EC2 underutilization",
                recommendation,
                evidence,
                tags,
                "Requires cost calculation",
            )
        )

    # Rule 4: high-cost + low-utilization (only with reliable cost data).
    monthly_cost = cost.get("monthly_cost") if isinstance(cost, dict) else None
    if (
        low_cpu
        and isinstance(monthly_cost, (int, float))
        and monthly_cost >= MEANINGFUL_MONTHLY_COST
    ):
        findings.append(
            _finding(
                instance_id,
                "high",
                "Potential high-cost underutilized resource",
                "Review rightsizing or scheduling options to reduce recurring "
                "infrastructure cost.",
                [
                    "Average CPUUtilization is %s%%." % cpu_average,
                    "Reported monthly cost is %s." % round(float(monthly_cost), 2),
                ],
                tags,
                "Requires cost calculation",
            )
        )

    return findings


def analyze_ec2_resources(
    instances: Sequence[Dict],
    metrics_by_instance: Optional[Dict[str, Dict]] = None,
    costs_by_instance: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Analyze many EC2 instances and return a flat list of findings."""
    metrics_by_instance = normalize_metrics(metrics_by_instance)
    costs_by_instance = costs_by_instance or {}
    findings: List[Dict] = []
    for instance in instances or []:
        instance_id = _instance_id(instance)
        findings.extend(
            analyze_ec2_resource(
                instance,
                metrics_by_instance.get(instance_id),
                costs_by_instance.get(instance_id),
            )
        )
    return findings


def _size_rank(instance_type: Optional[str]) -> Optional[int]:
    if not instance_type or "." not in instance_type:
        return None
    _, size = instance_type.split(".", 1)
    return INSTANCE_SIZE_ORDER.get(size)


def _is_capacity_increase(before_type: Optional[str], after_type: Optional[str]) -> bool:
    if not before_type or not after_type or before_type == after_type:
        return False
    before_rank = _size_rank(before_type)
    after_rank = _size_rank(after_type)
    if before_rank is None or after_rank is None:
        return False
    return after_rank > before_rank


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def analyze_iac_changes(
    changes: Sequence[Dict],
    metrics_by_address: Optional[Dict[str, Dict]] = None,
    infracost: Optional[Dict] = None,
) -> List[Dict]:
    """Deterministic findings for Terraform changes.

    Flags ``aws_instance`` capacity increases that coincide with low observed
    utilization (and, when available, a positive Infracost cost change). It
    never approves or applies a change; it only recommends human review.

    ``metrics_by_address`` accepts either a mapping keyed by resource id or a
    list of metric records (the ``/api/metrics/ec2`` shape); both are
    normalized internally. Missing metrics are treated as "no data" and never
    raise.
    """
    metrics_by_address = normalize_metrics(metrics_by_address)
    cost_change = None
    planned_monthly_cost = None
    infracost_ok = False
    infracost_resources: Dict[str, Dict] = {}
    if isinstance(infracost, dict):
        infracost_ok = infracost.get("status") == "ok"
        cost_change = _as_float(infracost.get("monthly_cost_change"))
        planned_monthly_cost = _as_float(infracost.get("planned_monthly_cost"))
        for resource in infracost.get("resources") or []:
            if isinstance(resource, dict) and resource.get("address"):
                infracost_resources[str(resource["address"])] = resource

    findings: List[Dict] = []
    has_resource_cost_data = bool(infracost_resources)
    if infracost_ok and planned_monthly_cost is not None and planned_monthly_cost >= MEANINGFUL_MONTHLY_COST:
        findings.append(
            _finding(
                "terraform",
                "medium",
                "Significant estimated monthly infrastructure cost",
                "Review the estimated recurring cost and confirm that the planned infrastructure is required.",
                ["Infracost estimated monthly cost is %s %s." % (
                    round(planned_monthly_cost, 2), infracost.get("currency", "USD")
                )],
                {},
                "Requires cost calculation",
                resource_type="terraform",
            )
        )
    if infracost_ok and (planned_monthly_cost is not None or has_resource_cost_data) and cost_change is not None and cost_change > 0:
        findings.append(
            _finding(
                "terraform",
                "medium",
                "Estimated monthly infrastructure cost increase",
                "Review the cost impact before approving the Terraform change.",
                ["Infracost monthly cost change is %s." % round(cost_change, 2)],
                {},
                "Requires cost calculation",
                resource_type="terraform",
            )
        )

    for change in changes or []:
        address = change.get("address")
        cost_resource = infracost_resources.get(address) or {}
        tags = cost_resource.get("tags") or (change.get("after") or {}).get("tags") or {}
        resource_cost = _as_float(cost_resource.get("monthly_cost"))
        metrics = metrics_by_address.get(address) or {}
        cpu_average = metrics.get("cpu_average")

        if cost_resource.get("tagging_findings"):
            for tagging_finding in cost_resource["tagging_findings"]:
                findings.append(_finding(
                    address,
                    "medium",
                    "Invalid or missing governance tags",
                    "Correct the tagging policy findings before approving the infrastructure change.",
                    ["Infracost tagging finding: %s." % tagging_finding],
                    tags,
                    0,
                    resource_type=change.get("resource_type") or "terraform",
                ))
        if cost_resource.get("policy_findings"):
            for policy_finding in cost_resource["policy_findings"]:
                findings.append(_finding(
                    address,
                    "medium",
                    "Infrastructure policy violation",
                    "Review and remediate the Infracost policy finding before approving the change.",
                    ["Infracost policy finding: %s." % policy_finding],
                    tags,
                    0,
                    resource_type=change.get("resource_type") or "terraform",
                ))
        if (
            cpu_average is not None
            and cpu_average < UNDERUTILIZED_CPU_THRESHOLD
            and resource_cost is not None
            and resource_cost >= MEANINGFUL_MONTHLY_COST
        ):
            findings.append(_finding(
                address,
                "high",
                "Potential high-cost underutilized resource",
                "Review rightsizing or scheduling options before approving the infrastructure change.",
                [
                    "Average CPUUtilization is %s%%." % cpu_average,
                    "Reported Infracost monthly cost is %s." % round(resource_cost, 2),
                ],
                tags,
                "Requires cost calculation",
                resource_type=change.get("resource_type") or "terraform",
            ))

        if change.get("resource_type") != "aws_instance":
            continue
        actions = change.get("actions") or []
        if not any(action in ("create", "update", "replace") for action in actions):
            continue

        before = change.get("before") or {}
        after = change.get("after") or {}
        before_type = before.get("instance_type")
        after_type = after.get("instance_type")
        if not _is_capacity_increase(before_type, after_type):
            continue

        low_cpu = cpu_average is not None and cpu_average < UNDERUTILIZED_CPU_THRESHOLD
        if not low_cpu:
            continue

        evidence = [
            "Terraform action(s): %s on %s." % (", ".join(actions), address),
            "Instance type change: %s -> %s." % (before_type, after_type),
            "Observed average CPUUtilization is %s%%." % cpu_average,
        ]
        if infracost_ok and cost_change is not None:
            evidence.append("Infracost monthly cost change is %s." % cost_change)
        severity = "high" if (infracost_ok and (cost_change or 0) > 0) else "medium"
        findings.append(_finding(
            address,
            severity,
            "Potential overprovisioning in infrastructure change",
            "Review the proposed capacity increase against observed workload utilization before approving the infrastructure change.",
            evidence,
            tags,
            "Requires cost calculation",
            resource_type="aws_instance",
        ))

    return findings
