"""Read-only CloudWatch metric collection for CloudOps AI.

Only read APIs are used (``GetMetricStatistics``, within the free tier). This module never creates
alarms and never modifies AWS resources. Missing datapoints are reported as
``None``; metric values are never fabricated.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import create_cloudwatch_client
from services.cloudwatch_stats import metric_series

__all__ = ["MetricsUnavailableError", "get_ec2_metrics"]

DEFAULT_PERIOD_HOURS = 24
_EC2_NAMESPACE = "AWS/EC2"
_CPU_METRIC = "CPUUtilization"


class MetricsUnavailableError(RuntimeError):
    """Raised when CloudWatch metric data cannot be retrieved."""


def _period_seconds(hours: int) -> int:
    """Return a whole-minute CloudWatch period targeting ~24 datapoints."""
    hours = max(1, int(hours))
    period = max(60, (hours * 3600) // 24)
    return max(60, (period // 60) * 60)


def get_ec2_metrics(
    instance_ids: Sequence[str],
    region_name: Optional[str] = None,
    hours: int = DEFAULT_PERIOD_HOURS,
) -> List[Dict]:
    """Return CPUUtilization metrics for the given EC2 instance ids.

    Uses CloudWatch ``GetMetricStatistics`` (read-only, free tier). Each result contains the
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
        for instance_id in ids:
            series = metric_series(
                client, _EC2_NAMESPACE, _CPU_METRIC,
                [{"Name": "InstanceId", "Value": instance_id}],
                ("Average", "Maximum"), period, start, end,
            )
            averages = [v for _, v in series["Average"]]
            peaks = [v for _, v in series["Maximum"]]
            if averages:
                results[instance_id]["cpu_average"] = round(sum(averages) / len(averages), 2)
                results[instance_id]["data_points"] = len(averages)
            if peaks:
                results[instance_id]["cpu_max"] = round(max(peaks), 2)
    except (ClientError, BotoCoreError) as error:
        raise MetricsUnavailableError("Failed to retrieve EC2 CloudWatch metrics") from error

    return [results[instance_id] for instance_id in ids]
