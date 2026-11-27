"""EC2 CloudWatch metrics via GetMetricStatistics (moto, no real AWS)."""

from datetime import datetime, timedelta, timezone

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from services import aws_metrics
from services.cloudwatch_stats import metric_series


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        yield boto3.client("cloudwatch", region_name="us-east-1")


def put_cpu(cw, instance_id, values):
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    cw.put_metric_data(Namespace="AWS/EC2", MetricData=[{
        "MetricName": "CPUUtilization",
        "Dimensions": [{"Name": "InstanceId", "Value": instance_id}],
        "Timestamp": now - timedelta(hours=hour) + timedelta(minutes=5),
        "Value": value,
    } for hour, value in enumerate(values, start=1)])


def test_average_and_peak_per_instance(aws):
    put_cpu(aws, "i-busy", [10.0, 20.0, 30.0])
    result = aws_metrics.get_ec2_metrics(["i-busy", "i-quiet"], hours=24)
    busy, quiet = result
    assert busy == {"instance_id": "i-busy", "period_hours": 24, "cpu_average": 20.0, "cpu_max": 30.0, "data_points": 3}
    # No datapoints: missing, never zero.
    assert quiet == {"instance_id": "i-quiet", "period_hours": 24, "cpu_average": None, "cpu_max": None, "data_points": 0}


def test_empty_ids_make_no_calls(monkeypatch):
    monkeypatch.setattr(aws_metrics, "create_cloudwatch_client", lambda region=None: pytest.fail("no call expected"))
    assert aws_metrics.get_ec2_metrics([]) == []


def test_access_denied_raises_metrics_unavailable(monkeypatch):
    class Denied:
        def get_metric_statistics(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetMetricStatistics")

    monkeypatch.setattr(aws_metrics, "create_cloudwatch_client", lambda region=None: Denied())
    with pytest.raises(aws_metrics.MetricsUnavailableError):
        aws_metrics.get_ec2_metrics(["i-1"])


@pytest.mark.parametrize("hours", [1, 24, 720])
def test_datapoints_per_call_stay_under_limit(hours):
    period = aws_metrics._period_seconds(hours)
    assert period % 60 == 0
    assert hours * 3600 / period <= 1440


def test_metric_series_is_newest_first_and_skips_missing_stats():
    class Fake:
        def get_metric_statistics(self, **kwargs):
            assert kwargs["Statistics"] == ["Average", "Maximum"]
            return {"Datapoints": [
                {"Timestamp": datetime(2026, 1, 1, 1, tzinfo=timezone.utc), "Average": 1, "Maximum": 2},
                {"Timestamp": datetime(2026, 1, 1, 3, tzinfo=timezone.utc), "Average": 3},
            ]}

    series = metric_series(Fake(), "AWS/EC2", "CPUUtilization", [], ("Average", "Maximum"), 60,
                           datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert [v for _, v in series["Average"]] == [3.0, 1.0]
    assert [v for _, v in series["Maximum"]] == [2.0]
