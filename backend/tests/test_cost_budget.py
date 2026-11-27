"""Shared cost snapshots and the hard monthly Cost Explorer cap."""

from datetime import date

import pytest

from services import cost_service, cost_store


@pytest.fixture(autouse=True)
def clear(monkeypatch):
    cost_service._cache.clear()
    cost_store._local_counts.clear()
    monkeypatch.setattr(cost_service, "_today_utc", lambda: date(2026, 11, 26))
    yield
    cost_service._cache.clear()
    cost_store._local_counts.clear()


class CountingCE:
    def __init__(self):
        self.calls = 0

    def get_cost_and_usage(self, **kwargs):
        self.calls += 1
        return {"ResultsByTime": [{"Groups": [
            {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "1.5", "Unit": "USD"}}}
        ]}]}


def install(monkeypatch):
    client = CountingCE()
    monkeypatch.setattr(cost_service, "create_cost_explorer_client", lambda region: client)
    return client


def test_snapshot_is_shared_across_process_restarts(monkeypatch):
    client = install(monkeypatch)
    first = cost_service.get_cost_summary()
    cost_service._cache.clear()  # simulate a cold start on another instance
    second = cost_service.get_cost_summary()
    assert client.calls == 1
    assert first == second and second["total_cost"] == 1.5


def test_budget_cap_serves_last_real_snapshot(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_CE_MONTHLY_CALL_LIMIT", "1")
    client = install(monkeypatch)
    cost_service.get_cost_summary()
    cost_service._cache.clear()
    monkeypatch.setattr(cost_service, "_today_utc", lambda: date(2026, 11, 27))
    stale = cost_service.get_cost_summary()
    assert client.calls == 1
    assert stale["end_inclusive"] == "2026-11-26"  # honest dates of the real data


def test_budget_cap_without_snapshot_is_clean_error(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_CE_MONTHLY_CALL_LIMIT", "0")
    client = install(monkeypatch)
    with pytest.raises(cost_service.CostServiceError) as error:
        cost_service.get_cost_summary()
    assert "budget" in str(error.value)
    assert client.calls == 0


def test_budget_resets_each_month(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_CE_MONTHLY_CALL_LIMIT", "1")
    assert cost_store.consume_budget(date(2026, 11, 26)) is True
    assert cost_store.consume_budget(date(2026, 11, 27)) is False
    assert cost_store.consume_budget(date(2026, 12, 1)) is True


def test_budget_default_is_75_calls():
    assert cost_service.cost_store.config.ce_monthly_call_limit() == 75
