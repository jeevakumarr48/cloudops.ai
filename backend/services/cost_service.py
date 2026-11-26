"""Read-only AWS Cost Explorer collection for CloudOps AI.

Uses ``GetCostAndUsage`` and ``GetCostForecast`` only. Costs are returned
exactly as AWS reports them; nothing is estimated, inferred, or fabricated.
Permission and availability problems are surfaced as clean errors or an
explicit ``available: false`` forecast state.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import COST_EXPLORER_REGION, create_cost_explorer_client
from services import cost_store

__all__ = [
    "CostServiceError",
    "SUPPORTED_PERIODS",
    "get_cost_summary",
    "get_cost_forecast",
]

SUPPORTED_PERIODS = ("daily", "monthly")

# Cache to avoid repeated Cost Explorer calls: CE bills $0.01 per request and
# AWS refreshes billing data only a few times a day, so a 24-hour default keeps
# the whole project inside its $1/month budget. Override with
# CLOUDOPS_COST_CACHE_SECONDS. This cache is per process; Vercel's CDN cache
# (see main.py) shares results across instances.
_CACHE_TTL_SECONDS = int(os.environ.get("CLOUDOPS_COST_CACHE_SECONDS", "86400"))
_cache: Dict[tuple, Tuple[float, Dict]] = {}
_cache_lock = threading.Lock()
# One lock per cache key so concurrent requests for the same data (the
# dashboard requests /api/overview and /api/costs together) make one billed
# Cost Explorer call instead of two.
_key_locks: Dict[tuple, threading.Lock] = {}

_DENIED_CODES = {
    "AccessDeniedException",
    "AccessDenied",
    "AuthFailure",
    "UnrecognizedClientException",
    "InvalidClientTokenId",
}


class CostServiceError(RuntimeError):
    """Raised when Cost Explorer data cannot be retrieved."""


def _today_utc() -> date:
    """Return today's date in UTC (Cost Explorer bills in UTC)."""
    return datetime.now(timezone.utc).date()


def _time_period(period: str) -> Tuple[date, date, str]:
    """Return (start, end_exclusive, granularity).

    Cost Explorer's ``TimePeriod.Start`` is inclusive and ``End`` is
    exclusive. ``end_exclusive`` is always the day after the last day that
    should be counted, so month-to-date covers the current day.
    """
    today = _today_utc()
    end_exclusive = today + timedelta(days=1)
    if period == "monthly":
        return today.replace(day=1), end_exclusive, "MONTHLY"
    return today - timedelta(days=29), end_exclusive, "DAILY"


def _cache_get(key: tuple) -> Optional[Dict]:
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if entry[0] <= now:
            _cache.pop(key, None)
            return None
        return entry[1]


def _cache_set(key: tuple, value: Dict) -> None:
    with _cache_lock:
        _cache[key] = (time.time() + _CACHE_TTL_SECONDS, value)


@contextmanager
def _single_flight(key: tuple):
    with _cache_lock:
        lock = _key_locks.setdefault(key, threading.Lock())
    with lock:
        yield


BUDGET_EXHAUSTED_MESSAGE = (
    "The monthly Cost Explorer request budget for this deployment has been "
    "reached and no earlier cost data is stored."
)


def _shared_fetch(cache_key: tuple, kind: str, params_key: str, fetch) -> Dict:
    """Serve from the shared store, else spend one budgeted CE request.

    Order: database snapshot for today -> billed request if under the
    monthly cap -> most recent real snapshot -> clean error. Must be called
    while holding the key's single-flight lock.
    """
    today = cache_key[-1]
    stored = cost_store.load(kind, params_key, today)
    if stored is not None:
        _cache_set(cache_key, stored)
        return stored
    if not cost_store.consume_budget(today):
        previous = cost_store.latest(kind, params_key)
        if previous is not None:
            _cache_set(cache_key, previous)
            return previous
        raise CostServiceError(BUDGET_EXHAUSTED_MESSAGE)
    result = fetch()
    cost_store.save(kind, params_key, today, result)
    return result


def _normalize_period(period: str) -> str:
    normalized = (period or "monthly").strip().lower()
    if normalized not in SUPPORTED_PERIODS:
        raise CostServiceError(
            "Unsupported period '%s'. Use one of: %s."
            % (period, ", ".join(SUPPORTED_PERIODS))
        )
    return normalized


def get_cost_summary(
    period: str = "monthly",
    group_by_service: bool = True,
    region_name: Optional[str] = COST_EXPLORER_REGION,
) -> Dict:
    """Return a normalized Cost Explorer summary.

    ``period`` is ``"daily"`` or ``"monthly"``. When ``group_by_service`` is
    true (the default) costs are grouped by the AWS ``SERVICE`` dimension.
    Pagination is followed via ``NextPageToken``.
    """
    normalized_period = _normalize_period(period)
    # The UTC date is part of the key so a cached month never crosses midnight
    # into the next billing day or month.
    cache_key = ("summary", normalized_period, bool(group_by_service), region_name, _today_utc())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    with _single_flight(cache_key):
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        return _shared_fetch(
            cache_key,
            "cost_summary",
            "%s:%s:%s" % (normalized_period, bool(group_by_service), region_name),
            lambda: _fetch_cost_summary(
                normalized_period, group_by_service, region_name, cache_key
            ),
        )


def _fetch_cost_summary(
    normalized_period: str,
    group_by_service: bool,
    region_name: Optional[str],
    cache_key: tuple,
) -> Dict:
    start, end_exclusive, granularity = _time_period(normalized_period)
    request: Dict = {
        "TimePeriod": {"Start": start.isoformat(), "End": end_exclusive.isoformat()},
        "Granularity": granularity,
        "Metrics": ["UnblendedCost"],
    }
    if group_by_service:
        request["GroupBy"] = [{"Type": "DIMENSION", "Key": "SERVICE"}]

    service_totals: Dict[str, float] = {}
    total = 0.0
    currency = "USD"

    try:
        client = create_cost_explorer_client(region_name or COST_EXPLORER_REGION)
        next_token: Optional[str] = None
        while True:
            call = dict(request)
            if next_token:
                call["NextPageToken"] = next_token
            response = client.get_cost_and_usage(**call)

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

            next_token = response.get("NextPageToken")
            if not next_token:
                break
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        if code in _DENIED_CODES:
            raise CostServiceError(
                "Cost Explorer access denied for the configured credentials."
            ) from error
        raise CostServiceError("Failed to retrieve cost data from Cost Explorer.") from error
    except BotoCoreError as error:
        raise CostServiceError("Failed to reach Cost Explorer.") from error

    services: List[Dict] = [
        {"service": name, "cost": round(value, 2)}
        for name, value in sorted(
            service_totals.items(), key=lambda item: item[1], reverse=True
        )
    ]

    result = {
        "period": normalized_period,
        "total_cost": round(total, 2),
        "currency": currency,
        "start": start.isoformat(),
        "end": end_exclusive.isoformat(),
        "end_inclusive": (end_exclusive - timedelta(days=1)).isoformat(),
        "services": services,
    }
    _cache_set(cache_key, result)
    return result


def get_cost_forecast(
    period: str = "monthly",
    region_name: Optional[str] = COST_EXPLORER_REGION,
) -> Dict:
    """Return AWS's own cost forecast (``GetCostForecast``).

    Never estimates a forecast locally. If AWS reports that forecast data is
    unavailable, a clean ``available: false`` payload is returned instead of
    a fabricated number.
    """
    normalized_period = _normalize_period(period)
    cache_key = ("forecast", normalized_period, region_name, _today_utc())
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    with _single_flight(cache_key):
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        return _shared_fetch(
            cache_key,
            "cost_forecast",
            "%s:%s" % (normalized_period, region_name),
            lambda: _fetch_cost_forecast(normalized_period, region_name, cache_key),
        )


def _fetch_cost_forecast(
    normalized_period: str, region_name: Optional[str], cache_key: tuple
) -> Dict:
    today = _today_utc()
    start = today + timedelta(days=1)
    end = start + timedelta(days=31) if normalized_period == "daily" else start + timedelta(days=62)
    granularity = "DAILY" if normalized_period == "daily" else "MONTHLY"

    try:
        client = create_cost_explorer_client(region_name or COST_EXPLORER_REGION)
        response = client.get_cost_forecast(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity=granularity,
            Metric="UNBLENDED_COST",
        )
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        if code == "DataUnavailableException":
            result = {
                "available": False,
                "reason": "AWS Cost Explorer forecast data is currently unavailable",
            }
            _cache_set(cache_key, result)
            return result
        if code in _DENIED_CODES:
            raise CostServiceError(
                "Cost Explorer access denied for the configured credentials."
            ) from error
        raise CostServiceError("Failed to retrieve the cost forecast.") from error
    except BotoCoreError as error:
        raise CostServiceError("Failed to reach Cost Explorer.") from error

    total = response.get("Total", {}) or {}
    currency = total.get("Unit", "USD")
    mean = float(total.get("Amount", 0) or 0)

    lower = 0.0
    upper = 0.0
    has_bounds = False
    for bucket in response.get("ForecastResultsByTime", []) or []:
        if bucket.get("PredictionIntervalLowerBound") is not None:
            lower += float(bucket.get("PredictionIntervalLowerBound") or 0)
            has_bounds = True
        if bucket.get("PredictionIntervalUpperBound") is not None:
            upper += float(bucket.get("PredictionIntervalUpperBound") or 0)
            has_bounds = True

    result = {
        "available": True,
        "period": normalized_period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "mean": round(mean, 2),
        "lower": round(lower, 2) if has_bounds else None,
        "upper": round(upper, 2) if has_bounds else None,
        "currency": currency,
    }
    _cache_set(cache_key, result)
    return result
