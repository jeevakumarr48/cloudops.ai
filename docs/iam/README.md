# CloudOps AI read-only IAM policy

`cloudops-readonly-policy.json` lists every AWS action the backend calls. All are
read-only: none can create, change or delete a resource, and none reads object
contents (`s3:GetObject` is deliberately absent).

Attach it to the IAM user or role whose credentials the backend uses. Missing
permissions do not break the app: each check reports `access_denied` and the
related governance rule reports `DATA_UNAVAILABLE` naming the action to grant.

Billed calls: `ce:GetCostAndUsage` and `ce:GetCostForecast` ($0.01 each, capped by
`CLOUDOPS_CE_MONTHLY_CALL_LIMIT`), `cloudwatch:GetMetricData` (about $0.01 per
1,000 metrics) and S3 bucket configuration reads (GET-class requests, about
$0.0004 per 1,000). The rest are free.
