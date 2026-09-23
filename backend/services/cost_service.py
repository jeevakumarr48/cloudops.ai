"""Read-only AWS Cost Explorer collection for CloudOps AI.

Only ``GetCostAndUsage`` is used. Costs are returned exactly as AWS reports
them; nothing is estimated, inferred, or fabricated. Permission problems are
surfaced as a clean :class:`CostServiceError`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import COST_EXPLORER_REGION, create_cost_explorer_client

__all__ = ["CostServiceError", "SUPPORTED_PERIODS", "get_cost_summary"]

SUPPORTED_PERIODS = ("daily", "monthly")

_DENIED_CODES = {
    "AccessDeniedException",
    "AccessDenied",
    "AuthFailure",
    "UnrecognizedClientException",
    "InvalidClientTokenId",
}


class CostServiceError(RuntimeError):
    """Raised when Cost Explorer data cannot be retrieved."""


def _time_period(period: str) -> Tuple[date, date, str]:
    """Return (start, end, granularity) for the requested period.

    ``end`` is exclusive, matching the Cost Explorer API.
    """
    today = datetime.now(timezone.utc).date()
    if period == "monthly":
        return today.replace(day=1), today + timedelta(days=1), "MONTHLY"
    return today - timedelta(days=29), today + timedelta(days=1), "DAILY"


def get_cost_summary(
    period: str = "monthly",
    group_by_service: bool = True,
    region_name: Optional[str] = COST_EXPLORER_REGION,
) -> Dict:
    """Return a normalized Cost Explorer summary.

    ``period`` is ``"daily"`` or ``"monthly"``. When ``group_by_service`` is
    true (the default) costs are grouped by the AWS ``SERVICE`` dimension.
    """
    normalized_period = (period or "monthly").strip().lower()
    if normalized_period not in SUPPORTED_PERIODS:
        raise CostServiceError(
            "Unsupported period '%s'. Use one of: %s."
            % (period, ", ".join(SUPPORTED_PERIODS))
        )

    start, end, granularity = _time_period(normalized_period)
    request: Dict = {
        "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
        "Granularity": granularity,
        "Metrics": ["UnblendedCost"],
    }
    if group_by_service:
        request["GroupBy"] = [{"Type": "DIMENSION", "Key": "SERVICE"}]

    try:
        client = create_cost_explorer_client(region_name or COST_EXPLORER_REGION)
        response = client.get_cost_and_usage(**request)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        if code in _DENIED_CODES:
            raise CostServiceError(
                "Cost Explorer access denied for the configured credentials."
            ) from error
        raise CostServiceError("Failed to retrieve cost data from Cost Explorer.") from error
    except BotoCoreError as error:
        raise CostServiceError("Failed to reach Cost Explorer.") from error

    service_totals: Dict[str, float] = {}
    total = 0.0
    currency = "USD"

    for bucket in response.get("ResultsByTime", []):
        if group_by_service:
            for group in bucket.get("Groups", []):
                keys = group.get("Keys") or []
                name = keys[0] if keys else "Unknown"
                amount = group.get("Metrics", {}).get("UnblendedCost", {})
                value = float(amount.get("Amount", 0) or 0)
                currency = amount.get("Unit", currency)
                service_totals[name] = service_totals.get(name, 0.0) + value
                total += value
        else:
            amount = bucket.get("Total", {}).get("UnblendedCost", {})
            value = float(amount.get("Amount", 0) or 0)
            currency = amount.get("Unit", currency)
            total += value

    services: List[Dict] = [
        {"service": name, "cost": round(value, 2)}
        for name, value in sorted(
            service_totals.items(), key=lambda item: item[1], reverse=True
        )
    ]

    return {
        "period": normalized_period,
        "total_cost": round(total, 2),
        "currency": currency,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "services": services,
    }
