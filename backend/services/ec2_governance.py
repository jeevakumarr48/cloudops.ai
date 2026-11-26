"""EC2 rules in the unified governance format.

The original ``decision_engine`` keeps serving ``/api/insights`` and
``/api/recommendations`` unchanged. These rules are stricter: utilization
needs 14 days of CloudWatch data with 80% coverage, and production
instances only ever get a review item.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from botocore.exceptions import BotoCoreError, ClientError

from services.governance_common import (
    CONFIRMED,
    INSUFFICIENT_EVIDENCE,
    NO_ISSUE,
    POTENTIAL,
    Evaluation,
    environment,
    is_production,
)

__all__ = ["METRIC_HOURS", "THRESHOLDS", "admin_port_exposure", "evaluate_instance"]

METRIC_HOURS = 14 * 24
THRESHOLDS = {
    "min_coverage": 0.8,
    "low_cpu_mean": 10.0,
    "low_cpu_peak": 40.0,
}
ADMIN_PORTS = {22: "SSH", 3389: "RDP"}
_OPEN_CIDRS = {"0.0.0.0/0", "::/0"}
_DENIED = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}


def _tags(instance: Dict) -> Dict[str, Any]:
    return {t.get("Key"): t.get("Value") for t in instance.get("Tags", []) if t.get("Key")}


def admin_port_exposure(ec2_client, instances: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """Map instance id -> admin ports open to the internet (one API call).

    Returns ``{"status": "ok"|"access_denied"|"error", "open": [...]}`` per
    instance with a public IP. Instances without a public IP are omitted.
    """
    public = [i for i in instances if i.get("PublicIpAddress")]
    group_ids = sorted({g["GroupId"] for i in public for g in i.get("SecurityGroups", []) if g.get("GroupId")})
    if not public:
        return {}
    try:
        groups = ec2_client.describe_security_groups(GroupIds=group_ids).get("SecurityGroups", []) if group_ids else []
        status = "ok"
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        groups, status = [], ("access_denied" if code in _DENIED else "error")
    except BotoCoreError:
        groups, status = [], "error"
    open_by_group: Dict[str, List[Dict[str, Any]]] = {}
    for group in groups:
        for permission in group.get("IpPermissions", []):
            cidrs = [r.get("CidrIp") for r in permission.get("IpRanges", [])]
            cidrs += [r.get("CidrIpv6") for r in permission.get("Ipv6Ranges", [])]
            if not any(c in _OPEN_CIDRS for c in cidrs):
                continue
            for port, name in ADMIN_PORTS.items():
                all_traffic = permission.get("IpProtocol") == "-1"
                in_range = (
                    permission.get("FromPort") is not None
                    and permission["FromPort"] <= port <= permission.get("ToPort", -1)
                )
                if all_traffic or in_range:
                    open_by_group.setdefault(group["GroupId"], []).append({"port": port, "service": name})
    result = {}
    for instance in public:
        found = []
        for group in instance.get("SecurityGroups", []):
            for item in open_by_group.get(group.get("GroupId"), []):
                found.append(dict(item, group_id=group["GroupId"]))
        result[instance["InstanceId"]] = {"status": status, "open": found}
    return result


def _ev(instance: Dict, rule_id: str, category: str, title: str) -> Evaluation:
    zone = (instance.get("Placement") or {}).get("AvailabilityZone")
    return Evaluation("EC2", instance.get("InstanceId"), zone[:-1] if zone else None,
                      rule_id, category, title, "aws:ec2")


def _rule_stopped(instance) -> Dict:
    ev = _ev(instance, "EC2_STOPPED_INSTANCE", "COST", "Instance is stopped")
    state = (instance.get("State") or {}).get("Name")
    ev.cite("ec2:DescribeInstances", "Instance state is %s." % state)
    if state != "stopped":
        return ev.result(NO_ISSUE)
    return ev.result(
        CONFIRMED, "MEDIUM",
        "A stopped instance has no compute charge, but its EBS volumes and any Elastic IPs are still billed. The amount is not calculated here.",
        "Confirm whether the instance is still needed; if not, snapshot and remove it after owner approval.",
        ["Identify the owner.", "If no longer needed, create a final snapshot.",
         "Terminate only after explicit approval."],
        missing_information=["Attached EBS volume sizes and costs."],
    )


def _rule_owner_tag(instance) -> Dict:
    ev = _ev(instance, "EC2_MISSING_OWNER_TAG", "GOVERNANCE", "Owner tag is missing")
    tags = _tags(instance)
    if "Owner" in tags or "owner" in tags:
        ev.cite("ec2:DescribeInstances", "Owner tag is %s." % (tags.get("Owner") or tags.get("owner")))
        return ev.result(NO_ISSUE)
    ev.cite("ec2:DescribeInstances", "No Owner tag.")
    return ev.result(
        CONFIRMED, "LOW", "Nobody is recorded as accountable for this instance.",
        "Add an Owner tag.", ["Add an Owner tag with a team or person."],
    )


def _rule_environment_tag(instance) -> Dict:
    ev = _ev(instance, "EC2_MISSING_ENVIRONMENT_TAG", "GOVERNANCE", "Environment tag is missing")
    env = environment(_tags(instance))
    if env:
        ev.cite("ec2:DescribeInstances", "Environment tag is %s." % env)
        return ev.result(NO_ISSUE)
    ev.cite("ec2:DescribeInstances", "No Environment tag.")
    return ev.result(
        CONFIRMED, "LOW",
        "Without an environment, rules cannot tell production from development, so recommendations are more cautious.",
        "Add an Environment tag (for example production, staging, development).",
        ["Add an Environment tag."],
    )


def _rule_admin_ports(instance, exposure: Optional[Dict]) -> Dict:
    ev = _ev(instance, "EC2_OPEN_ADMIN_PORTS", "SECURITY", "SSH or RDP open to the internet")
    if not instance.get("PublicIpAddress"):
        ev.cite("ec2:DescribeInstances", "Instance has no public IPv4 address.")
        return ev.result(NO_ISSUE)
    ev.cite("ec2:DescribeInstances", "Instance has a public IPv4 address.")
    if not exposure or exposure.get("status") != "ok":
        return ev.unavailable("security group rules", (exposure or {}).get("status"), "ec2:DescribeSecurityGroups")
    if not exposure["open"]:
        ev.cite("ec2:DescribeSecurityGroups", "No rule allows SSH (22) or RDP (3389) from 0.0.0.0/0 or ::/0.")
        return ev.result(NO_ISSUE)
    for item in exposure["open"]:
        ev.cite("ec2:DescribeSecurityGroups", "%s allows %s (port %d) from the internet." % (item["group_id"], item["service"], item["port"]))
    return ev.result(
        CONFIRMED, "HIGH",
        "Anyone on the internet can attempt to log in to this instance.",
        "Restrict administrative access to known IP ranges or use Session Manager instead of open ports.",
        ["Replace 0.0.0.0/0 with your own IP range, or remove the rule.",
         "Consider AWS Systems Manager Session Manager, which needs no inbound port."],
    )


def _rule_utilization(instance, metrics: Optional[Dict], metrics_status: str) -> Dict:
    ev = _ev(instance, "EC2_LOW_UTILIZATION", "UTILIZATION", "Instance may be overprovisioned")
    if metrics_status != "ok":
        return ev.unavailable("CloudWatch CPU metrics", "error", "cloudwatch:GetMetricData")
    state = (instance.get("State") or {}).get("Name")
    if state != "running":
        ev.cite("ec2:DescribeInstances", "Instance state is %s." % state)
        return ev.result(INSUFFICIENT_EVIDENCE, "INFO", "Utilization is only judged for running instances.", confidence="low")
    metrics = metrics or {}
    points = metrics.get("data_points") or 0
    coverage = points / 24.0
    ev.cite("cloudwatch:AWS/EC2 CPUUtilization",
            "%d of 24 expected datapoints (each ~14 hours) over the last 14 days (%.0f%% coverage)." % (points, coverage * 100))
    if coverage < THRESHOLDS["min_coverage"] or metrics.get("cpu_average") is None:
        return ev.result(
            INSUFFICIENT_EVIDENCE, "INFO",
            "Not enough metric history to judge utilization; 14 days with 80% coverage is required.",
            confidence="low", missing_information=["More CloudWatch history."],
        )
    mean, peak = metrics["cpu_average"], metrics.get("cpu_max")
    ev.cite("cloudwatch:AWS/EC2 CPUUtilization", "CPU mean %s%%, peak %s%%." % (mean, peak))
    if not (mean < THRESHOLDS["low_cpu_mean"] and peak is not None and peak < THRESHOLDS["low_cpu_peak"]):
        return ev.result(NO_ISSUE)
    prod = is_production(_tags(instance))
    ev.cite("ec2:DescribeInstances", "Instance type %s; environment %s." % (
        instance.get("InstanceType"), environment(_tags(instance)) or "untagged"))
    missing = ["Memory use (needs the CloudWatch agent).", "Network and disk throughput needs.",
               "Peaks outside the 14-day window."]
    steps = ["Check memory, network and disk needs, not just CPU.",
             "Test a smaller type in a non-production copy first.",
             "Resize only with owner approval, during a maintenance window (requires a stop/start)."]
    if prod:
        return ev.result(
            POTENTIAL, "LOW",
            "CPU has been low for 14 days, but this is a production instance; CPU alone is not enough to resize it safely.",
            "Treat as a review item with the owning team.", steps, confidence="low", missing_information=missing,
        )
    return ev.result(
        POTENTIAL, "MEDIUM" if prod is False else "LOW",
        "CPU stayed low for the whole window, so a smaller instance type or a schedule may be sufficient.",
        "Evaluate a smaller instance type or stopping it outside working hours.",
        steps, confidence="medium" if prod is False else "low", missing_information=missing,
    )


def evaluate_instance(instance: Dict, metrics: Optional[Dict], metrics_status: str,
                      exposure: Optional[Dict]) -> List[Dict[str, Any]]:
    return [
        _rule_admin_ports(instance, exposure),
        _rule_stopped(instance),
        _rule_utilization(instance, metrics, metrics_status),
        _rule_owner_tag(instance),
        _rule_environment_tag(instance),
    ]
