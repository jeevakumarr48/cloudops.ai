"""Tests for the Phase 1 caches that limit billed and repeated AWS calls."""

import threading
import time

import pytest

import aws_client
from services import ai_explainer, cost_service


@pytest.fixture(autouse=True)
def reset_caches():
    cost_service._cache.clear()
    aws_client._discovery_cache.clear()
    ai_explainer._llm_cache.clear()
    yield
    cost_service._cache.clear()
    aws_client._discovery_cache.clear()
    ai_explainer._llm_cache.clear()


class SlowCostExplorer:
    """Counts calls and sleeps so concurrent requests overlap."""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def get_cost_and_usage(self, **kwargs):
        with self._lock:
            self.calls += 1
        time.sleep(0.05)
        return {"ResultsByTime": [{"Groups": []}]}


def test_concurrent_cost_requests_make_one_billed_call(monkeypatch):
    client = SlowCostExplorer()
    monkeypatch.setattr(cost_service, "create_cost_explorer_client", lambda region: client)
    threads = [threading.Thread(target=cost_service.get_cost_summary) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert client.calls == 1


def test_cost_cache_default_is_one_day():
    assert cost_service._CACHE_TTL_SECONDS == 86400


class FakePaginator:
    def __init__(self, counter):
        self.counter = counter

    def paginate(self):
        self.counter["calls"] += 1
        return [{"Reservations": [{"Instances": [{"InstanceId": "i-1"}]}]}]


class FakeEC2:
    def __init__(self, counter):
        self.counter = counter

    def get_paginator(self, name):
        assert name == "describe_instances"
        return FakePaginator(self.counter)


def test_discovery_is_cached_and_returns_copies(monkeypatch):
    counter = {"calls": 0}
    monkeypatch.setattr(aws_client, "create_ec2_client", lambda region=None: FakeEC2(counter))
    first = aws_client.discover_ec2_instances()
    first[0]["InstanceId"] = "mutated"
    second = aws_client.discover_ec2_instances()
    assert counter["calls"] == 1
    assert second == [{"InstanceId": "i-1"}]


def test_discovery_failures_are_not_cached(monkeypatch):
    from botocore.exceptions import ClientError

    class DeniedEC2:
        def get_paginator(self, name):
            raise ClientError({"Error": {"Code": "UnauthorizedOperation"}}, "DescribeInstances")

    monkeypatch.setattr(aws_client, "create_ec2_client", lambda region=None: DeniedEC2())
    with pytest.raises(aws_client.AWSAccessError):
        aws_client.discover_ec2_instances()
    assert aws_client._discovery_cache == {}


def test_llm_explanation_is_reused_for_same_findings(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_AI_API_KEY", "test-key-not-real")
    calls = {"n": 0}

    def fake_llm(config, findings):
        calls["n"] += 1
        return {"summary": "s", "findings": [{"issue": "x", "explanation": "e"}]}

    monkeypatch.setattr(ai_explainer, "_call_llm", fake_llm)
    findings = [{"issue": "x", "severity": "low", "evidence": ["a"]}]
    assert ai_explainer.explain_findings(findings)["source"] == "llm"
    assert ai_explainer.explain_findings(findings)["source"] == "llm"
    assert calls["n"] == 1
    ai_explainer.explain_findings([{"issue": "y", "severity": "low"}])
    assert calls["n"] == 2


def test_llm_failure_is_not_cached(monkeypatch):
    monkeypatch.setenv("CLOUDOPS_AI_API_KEY", "test-key-not-real")

    def broken(config, findings):
        raise ValueError("bad provider output")

    monkeypatch.setattr(ai_explainer, "_call_llm", broken)
    result = ai_explainer.explain_findings([{"issue": "x", "severity": "low"}])
    assert result["source"] == "deterministic_fallback"
    assert ai_explainer._llm_cache == {}


def test_cost_cache_does_not_cross_utc_midnight(monkeypatch):
    from datetime import date

    client = SlowCostExplorer()
    monkeypatch.setattr(cost_service, "create_cost_explorer_client", lambda region: client)
    monkeypatch.setattr(cost_service, "_today_utc", lambda: date(2026, 11, 30))
    cost_service.get_cost_summary()
    cost_service.get_cost_summary()
    monkeypatch.setattr(cost_service, "_today_utc", lambda: date(2026, 12, 1))
    cost_service.get_cost_summary()
    assert client.calls == 2
