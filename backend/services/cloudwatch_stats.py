"""Free-tier CloudWatch reads.

``GetMetricData`` is billed per metric requested ($0.01 per 1,000) and is
excluded from the CloudWatch free tier. ``GetMetricStatistics`` counts
towards the always-free allowance of 1 million API requests a month, so all
metric reads go through it to keep the platform's own AWS bill at zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple

__all__ = ["metric_series"]

Series = List[Tuple[datetime, float]]


def metric_series(
    client: Any,
    namespace: str,
    metric: str,
    dimensions: Sequence[Dict[str, str]],
    stats: Sequence[str],
    period: int,
    start: datetime,
    end: datetime,
) -> Dict[str, Series]:
    """Return ``{stat: [(timestamp, value), ...]}``, newest first.

    One ``GetMetricStatistics`` call per metric (all requested statistics in
    the same call). Missing datapoints are simply absent, never zero-filled.
    Errors propagate so callers keep their own error handling.
    """
    response = client.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric,
        Dimensions=list(dimensions),
        StartTime=start,
        EndTime=end,
        Period=period,
        Statistics=list(stats),
    )
    points = sorted(response.get("Datapoints") or [], key=lambda p: p["Timestamp"], reverse=True)
    return {
        stat: [(p["Timestamp"], float(p[stat])) for p in points if p.get(stat) is not None]
        for stat in stats
    }
