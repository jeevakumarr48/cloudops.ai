import boto3

ce = boto3.client("ce", region_name="us-east-1")

response = ce.get_cost_and_usage(
    TimePeriod={
        "Start": "2026-08-01",
        "End": "2026-09-01"
    },
    Granularity="MONTHLY",
    Metrics=["UnblendedCost"]
)

print(response)