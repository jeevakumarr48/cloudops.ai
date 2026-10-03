"""Unit tests for the Cost Explorer service (mocked, no AWS calls)."""

from datetime import date

import pytest
from botocore.exceptions import ClientError

from services import cost_service


@pytest.fixture(autouse=True)
def clear_cache():
    cost_service._cache.clear()
    yield
    cost_service._cache.clear()


class FakeCostExplorer:
    def __init__(self, usage_pages=None, forecast=None, forecast_error=None):
        self._usage_pages = usage_pages or []
        self._forecast = forecast
        self._forecast_error = forecast_error
        self.usage_calls = 0

    def get_cost_and_usage(self, **kwargs):
        page = self._usage_pages[self.usage_calls]
        self.usage_calls += 1
        return page

    def get_cost_forecast(self, **kwargs):
        if self._forecast_error is not None:
            raise self._forecast_error
        return self._forecast


def install(monkeypatch, client, today=None):
    monkeypatch.setattr(cost_service, "create_cost_explorer_client", lambda region: client)
    if today is not None:
        monkeypatch.setattr(cost_service, "_today_utc", lambda: today)


def bucket(groups):
    return {
        "ResultsByTime": [
            {
                "Groups": [
                    {
                        "Keys": [name],
                        "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
                    }
                    for name, amount in groups
                ]
            }
        ]
    }


def test_time_period_monthly_is_inclusive_of_today(monkeypatch):
    install(monkeypatch, FakeCostExplorer(), today=date(2026, 10, 4))
    start, end, granularity = cost_service._time_period("monthly")
    assert start == date(2026, 10, 1)
    assert end == date(2026, 10, 5)  # exclusive end -> covers Oct 1..Oct 4
    assert granularity == "MONTHLY"


def test_time_period_daily_covers_30_days(monkeypatch):
    install(monkeypatch, FakeCostExplorer(), today=date(2026, 10, 4))
    start, end, granularity = cost_service._time_period("daily")
    assert (end - start).days == 30
    assert granularity == "DAILY"


def test_summary_parses_groups_and_reports_inclusive_end(monkeypatch):
    client = FakeCostExplorer(usage_pages=[bucket([("Amazon Simple Storage Service", "0.15"), ("Tax", "0.03")])])
    install(monkeypatch, client, today=date(2026, 10, 4))
    result = cost_service.get_cost_summary("monthly")
    assert result["total_cost"] == 0.18
    assert result["start"] == "2026-10-01"
    assert result["end"] == "2026-10-05"
    assert result["end_inclusive"] == "2026-10-04"
    assert result["services"][0] == {"service": "Amazon Simple Storage Service", "cost": 0.15}


def test_summary_follows_pagination(monkeypatch):
    page1 = bucket([("S3", "0.10")])
    page1["NextPageToken"] = "token-2"
    page2 = bucket([("CloudWatch", "0.05")])
    client = FakeCostExplorer(usage_pages=[page1, page2])
    install(monkeypatch, client, today=date(2026, 10, 4))
    result = cost_service.get_cost_summary("monthly")
    assert client.usage_calls == 2
    assert result["total_cost"] == 0.15


def test_real_zero_cost_is_not_treated_as_unavailable(monkeypatch):
    client = FakeCostExplorer(usage_pages=[bucket([("S3", "0"), ("KMS", "0")])])
    install(monkeypatch, client, today=date(2026, 10, 4))
    result = cost_service.get_cost_summary("monthly")
    assert result["total_cost"] == 0.0
    assert len(result["services"]) == 2  # zero-cost services are real, not hidden


def test_summary_caches_repeated_calls(monkeypatch):
    client = FakeCostExplorer(usage_pages=[bucket([("S3", "0.10")])])
    install(monkeypatch, client, today=date(2026, 10, 4))
    cost_service.get_cost_summary("monthly")
    cost_service.get_cost_summary("monthly")
    assert client.usage_calls == 1  # second call served from cache


def test_forecast_returns_real_values(monkeypatch):
    forecast = {
        "Total": {"Amount": "12.34", "Unit": "USD"},
        "ForecastResultsByTime": [
            {"MeanValue": "12.34", "PredictionIntervalLowerBound": "10.00", "PredictionIntervalUpperBound": "15.00"}
        ],
    }
    install(monkeypatch, FakeCostExplorer(forecast=forecast), today=date(2026, 10, 4))
    result = cost_service.get_cost_forecast("monthly")
    assert result["available"] is True
    assert result["mean"] == 12.34
    assert result["lower"] == 10.0
    assert result["upper"] == 15.0
    assert result["currency"] == "USD"


def test_forecast_unavailable_is_clean(monkeypatch):
    error = ClientError({"Error": {"Code": "DataUnavailableException", "Message": "no data"}}, "GetCostForecast")
    install(monkeypatch, FakeCostExplorer(forecast_error=error), today=date(2026, 10, 4))
    result = cost_service.get_cost_forecast("monthly")
    assert result["available"] is False
    assert "unavailable" in result["reason"].lower()
    assert "mean" not in result


def test_unsupported_period_raises():
    with pytest.raises(cost_service.CostServiceError):
        cost_service.get_cost_summary("yearly")
