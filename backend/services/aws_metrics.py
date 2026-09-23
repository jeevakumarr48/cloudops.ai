"""Read-only CloudWatch metric collection for CloudOps AI.

Only read APIs are used (``GetMetricData``). This module never creates
alarms and never modifies AWS resources. Missing datapoints are reported as
``None``; metric values are never fabricated.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import create_cloudwatch_client

__all__ = ["MetricsUnavailableError", "get_ec2_metrics"]

DEFAULT_PERIOD_HOURS = 24
# GetMetricData accepts at most 500 metric queries per call and two queries
# are issued per instance (average + maximum).
_MAX_INSTANCES_PER_CALL = 250
_EC2_NAMESPACE = "AWS/EC2"
_CPU_METRIC = "CPUUtilization"


class MetricsUnavailableError(RuntimeError):
    """Raised when CloudWatch metric data cannot be retrieved."""


def _period_seconds(hours: int) -> int:
    """Return a whole-minute CloudWatch period targeting ~24 datapoints."""
    hours = max(1, int(hours))
    period = max(60, (hours * 3600) // 24)
    return max(60, (period // 60) * 60)


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _query(query_id: str, instance_id: str, stat: str, period: int) -> Dict:
    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {
                "Namespace": _EC2_NAMESPACE,
                "MetricName": _CPU_METRIC,
                "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
            },
            "Period": period,
            "Stat": stat,
        },
        "ReturnData": True,
    }


def get_ec2_metrics(
    instance_ids: Sequence[str],
    region_name: Optional[str] = None,
    hours: int = DEFAULT_PERIOD_HOURS,
) -> List[Dict]:
    """Return CPUUtilization metrics for the given EC2 instance ids.

    Uses CloudWatch ``GetMetricData`` (read-only). Each result contains the
    mean and peak ``CPUUtilization`` observed over the window. Instances
    with no datapoints return ``cpu_average=None``, ``cpu_max=None`` and
    ``data_points=0`` rather than invented values.
    """
    ids = [i for i in (instance_ids or []) if i]
    results: Dict[str, Dict] = {
        instance_id: {
            "instance_id": instance_id,
            "period_hours": int(hours),
            "cpu_average": None,
            "cpu_max": None,
            "data_points": 0,
        }
        for instance_id in ids
    }
    if not ids:
        return []

    period = _period_seconds(hours)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=max(1, int(hours)))

    try:
        client = create_cloudwatch_client(region_name)
        for chunk in _chunks(ids, _MAX_INSTANCES_PER_CALL):
            queries: List[Dict] = []
            for index, instance_id in enumerate(chunk):
                queries.append(_query(f"i{index}", instance_id, "Average", period))
                queries.append(_query(f"m{index}", instance_id, "Maximum", period))

            response = client.get_metric_data(
                MetricDataQueries=queries,
                StartTime=start,
                EndTime=end,
                ScanBy="TimestampDescending",
            )

            for item in response.get("MetricDataResults", []):
                query_id = item.get("Id", "")
                if len(query_id) < 2 or not query_id[1:].isdigit():
                    continue
                index = int(query_id[1:])
                if index >= len(chunk):
                    continue
                instance_id = chunk[index]
                values = [v for v in item.get("Values", []) if v is not None]
                if not values:
                    continue
                if query_id.startswith("i"):
                    results[instance_id]["cpu_average"] = round(sum(values) / len(values), 2)
                    results[instance_id]["data_points"] = len(values)
                elif query_id.startswith("m"):
                    results[instance_id]["cpu_max"] = round(max(values), 2)
    except (ClientError, BotoCoreError) as error:
        raise MetricsUnavailableError("Failed to retrieve EC2 CloudWatch metrics") from error

    return [results[instance_id] for instance_id in ids]
