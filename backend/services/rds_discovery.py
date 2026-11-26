"""Read-only RDS instance discovery for CloudOps AI.

Collects configuration from ``DescribeDBInstances`` (paginated), inbound
rules of the attached VPC security groups (``DescribeSecurityGroups``) and
14 days of hourly CloudWatch metrics. Metric coverage is reported so rules
can refuse to judge utilization on thin data. A missing metric is ``None``,
never zero. Nothing here writes to AWS.
"""

from __future__ import annotations

import copy
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

__all__ = ["RDSAccessError", "discover_rds_instances", "clear_cache", "METRIC_WINDOW_DAYS"]

METRIC_WINDOW_DAYS = 14
_PERIOD_SECONDS = 3600
_DENIED_CODES = {
    "AccessDenied", "AccessDeniedException", "UnauthorizedOperation",
    "InvalidClientTokenId", "UnrecognizedClientException", "ExpiredToken",
}
_CACHE_TTL_SECONDS = int(os.environ.get("CLOUDOPS_RDS_CACHE_SECONDS", "900"))
_REFRESH_COOLDOWN_SECONDS = 60
_BOTO_CONFIG = Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=5, read_timeout=20)
_OPEN_CIDRS = {"0.0.0.0/0", "::/0"}

_cache: Dict[Optional[str], Tuple[float, Dict, float]] = {}
_cache_lock = threading.Lock()


class RDSAccessError(RuntimeError):
    """Raised when the DB instance list itself cannot be retrieved."""


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _client(service: str, region: Optional[str] = None):
    return boto3.client(service, region_name=region, config=_BOTO_CONFIG)


def _classify(error: Exception) -> str:
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "")
        return "access_denied" if code in _DENIED_CODES else "error"
    return "error"


def _percentile(values: Sequence[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(pct / 100.0 * len(ordered)) - 1)
    return ordered[rank]


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _security_groups(region: Optional[str], group_ids: List[str], port: Optional[int]) -> Dict[str, Any]:
    """Inbound rules of the DB's security groups that are open to the internet."""
    if not group_ids:
        return {"status": "ok", "open_to_internet": [], "group_ids": []}
    try:
        response = _client("ec2", region).describe_security_groups(GroupIds=group_ids)
    except (ClientError, BotoCoreError) as error:
        return {"status": _classify(error), "open_to_internet": None, "group_ids": group_ids}
    open_rules = []
    for group in response.get("SecurityGroups", []):
        for permission in group.get("IpPermissions", []):
            cidrs = [r.get("CidrIp") for r in permission.get("IpRanges", [])]
            cidrs += [r.get("CidrIpv6") for r in permission.get("Ipv6Ranges", [])]
            exposed = sorted(c for c in cidrs if c in _OPEN_CIDRS)
            if not exposed:
                continue
            protocol = permission.get("IpProtocol")
            from_port, to_port = permission.get("FromPort"), permission.get("ToPort")
            covers_port = protocol == "-1" or port is None or (
                from_port is not None and to_port is not None and from_port <= port <= to_port
            )
            if covers_port:
                open_rules.append({
                    "group_id": group.get("GroupId"),
                    "protocol": protocol,
                    "from_port": from_port,
                    "to_port": to_port,
                    "cidrs": exposed,
                })
    return {"status": "ok", "open_to_internet": open_rules, "group_ids": group_ids}


def _metrics(region: Optional[str], identifier: str) -> Dict[str, Any]:
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=METRIC_WINDOW_DAYS)
    expected = METRIC_WINDOW_DAYS * 24

    def query(query_id: str, metric: str, stat: str):
        return {
            "Id": query_id,
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/RDS",
                    "MetricName": metric,
                    "Dimensions": [{"Name": "DBInstanceIdentifier", "Value": identifier}],
                },
                "Period": _PERIOD_SECONDS,
                "Stat": stat,
            },
            "ReturnData": True,
        }

    queries = [
        query("cpuavg", "CPUUtilization", "Average"),
        query("cpumax", "CPUUtilization", "Maximum"),
        query("conn", "DatabaseConnections", "Maximum"),
        query("freestorage", "FreeStorageSpace", "Minimum"),
        query("freemem", "FreeableMemory", "Minimum"),
    ]
    values: Dict[str, List[Tuple[datetime, float]]] = {q["Id"]: [] for q in queries}
    try:
        client = _client("cloudwatch", region)
        token = None
        while True:
            kwargs = dict(MetricDataQueries=queries, StartTime=start, EndTime=end, ScanBy="TimestampDescending")
            if token:
                kwargs["NextToken"] = token
            response = client.get_metric_data(**kwargs)
            for item in response.get("MetricDataResults", []):
                values.setdefault(item.get("Id"), []).extend(
                    zip(item.get("Timestamps") or [], item.get("Values") or [])
                )
            token = response.get("NextToken")
            if not token:
                break
    except (ClientError, BotoCoreError) as error:
        return {"status": _classify(error), "window_days": METRIC_WINDOW_DAYS, "note": "CloudWatch metrics could not be read."}

    cpu_avg = [v for _, v in values["cpuavg"]]
    cpu_max = [v for _, v in values["cpumax"]]
    conn = [v for _, v in values["conn"]]
    free_storage = sorted(values["freestorage"], key=lambda pair: pair[0], reverse=True)
    free_mem = [v for _, v in values["freemem"]]
    hours = len(cpu_avg)
    return {
        "status": "ok" if hours else "no_data",
        "window_days": METRIC_WINDOW_DAYS,
        "expected_hours": expected,
        "observed_hours": hours,
        "coverage": round(hours / expected, 3),
        "cpu_mean": _round(sum(cpu_avg) / hours) if hours else None,
        "cpu_p95": _round(_percentile(cpu_avg, 95)),
        "cpu_peak": _round(max(cpu_max)) if cpu_max else None,
        "connections_peak": int(max(conn)) if conn else None,
        "free_storage_bytes_latest": int(free_storage[0][1]) if free_storage else None,
        "free_storage_as_of": free_storage[0][0].isoformat() if free_storage else None,
        "freeable_memory_bytes_min": int(min(free_mem)) if free_mem else None,
        "note": None if hours else "No CPU datapoints in the window; this does not mean the database is idle.",
    }


def _instance_record(raw: Dict[str, Any], region: Optional[str]) -> Dict[str, Any]:
    identifier = raw.get("DBInstanceIdentifier")
    endpoint = raw.get("Endpoint") or {}
    port = endpoint.get("Port") or raw.get("DbInstancePort") or None
    group_ids = [g.get("VpcSecurityGroupId") for g in raw.get("VpcSecurityGroups", []) if g.get("VpcSecurityGroupId")]
    tags = {t.get("Key"): t.get("Value") for t in raw.get("TagList", []) if t.get("Key")}
    record = {
        "identifier": identifier,
        "arn": raw.get("DBInstanceArn"),
        "engine": raw.get("Engine"),
        "engine_version": raw.get("EngineVersion"),
        "instance_class": raw.get("DBInstanceClass"),
        "status": raw.get("DBInstanceStatus"),
        "region": region,
        "availability_zone": raw.get("AvailabilityZone"),
        "cluster_identifier": raw.get("DBClusterIdentifier"),
        "multi_az": bool(raw.get("MultiAZ")),
        "publicly_accessible": bool(raw.get("PubliclyAccessible")),
        "storage_encrypted": bool(raw.get("StorageEncrypted")),
        "storage_type": raw.get("StorageType"),
        "allocated_storage_gib": raw.get("AllocatedStorage"),
        "max_allocated_storage_gib": raw.get("MaxAllocatedStorage"),
        "iops": raw.get("Iops"),
        "backup_retention_days": raw.get("BackupRetentionPeriod"),
        "deletion_protection": bool(raw.get("DeletionProtection")),
        "auto_minor_version_upgrade": bool(raw.get("AutoMinorVersionUpgrade")),
        "port": port,
        "tags": tags,
        "created_at": raw["InstanceCreateTime"].isoformat() if raw.get("InstanceCreateTime") else None,
    }
    record["security_groups"] = _security_groups(region, group_ids, port)
    record["metrics"] = _metrics(region, identifier)
    return record


def discover_rds_instances(region: Optional[str] = None, refresh: bool = False) -> Dict[str, Any]:
    """Return every DB instance in ``region`` (default region if ``None``).

    Raises:
        RDSAccessError: if ``DescribeDBInstances`` fails. Security group and
        metric failures are reported per instance instead.
    """
    now = time.time()
    with _cache_lock:
        entry = _cache.get(region)
        if entry is not None and (
            entry[0] > now if not refresh else entry[2] > now - _REFRESH_COOLDOWN_SECONDS
        ):
            return copy.deepcopy(entry[1])

    client = _client("rds", region)
    effective_region = region or client.meta.region_name
    raw_instances: List[Dict] = []
    try:
        for page in client.get_paginator("describe_db_instances").paginate():
            raw_instances.extend(page.get("DBInstances", []))
    except ClientError as error:
        if _classify(error) == "access_denied":
            raise RDSAccessError("RDS describe access is not permitted for the configured credentials.") from error
        raise RDSAccessError("Failed to retrieve RDS instances.") from error
    except BotoCoreError as error:
        raise RDSAccessError("Failed to reach Amazon RDS.") from error

    instances = sorted(
        (_instance_record(raw, effective_region) for raw in raw_instances),
        key=lambda record: record["identifier"] or "",
    )
    result = {
        "status": "ok",
        "region": effective_region,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_instances": len(instances),
        "instances": instances,
    }
    with _cache_lock:
        _cache[region] = (time.time() + _CACHE_TTL_SECONDS, copy.deepcopy(result), time.time())
    return result
