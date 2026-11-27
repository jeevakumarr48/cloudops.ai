# CloudOps AI read-only IAM policy

`cloudops-readonly-policy.json` lists every AWS action the backend calls. All are
read-only: none can create, change or delete a resource, and none reads object
contents (`s3:GetObject` is deliberately absent).

Attach it to the IAM user or role whose credentials the backend uses. Missing
permissions do not break the app: each check reports `access_denied` and the
related governance rule reports `DATA_UNAVAILABLE` naming the action to grant.

Billed calls: `ce:GetCostAndUsage` and `ce:GetCostForecast` ($0.01 each, capped by
`CLOUDOPS_CE_MONTHLY_CALL_LIMIT`) and S3 bucket configuration reads (GET-class
requests, about $0.0004 per 1,000). The rest are free: CloudWatch metrics are
read with `cloudwatch:GetMetricStatistics`, which is covered by CloudWatch's
free tier of 1 million API requests a month (`GetMetricData` is not, so the
backend does not call it).

## Credentials: prefer a role, ideally with no stored keys

The backend reads credentials through `core/aws_session.py`. Choose one:

1. **Vercel OIDC federation (recommended, no AWS keys anywhere).** The
   Terraform in [`infra/terraform/aws`](../../infra/terraform/README.md)
   creates all of this for you; the manual steps are: in AWS, add
   the identity provider `oidc.vercel.com/TEAM_SLUG` (team issuer mode,
   audience `https://vercel.com/TEAM_SLUG`), create a role with
   `cloudops-readonly-policy.json` attached and the trust policy in
   `trust-policy-vercel-oidc.json` (replace the placeholders; `sub` pins it to
   the API project's production environment). In the Vercel API project, enable
   OIDC federation, set `CLOUDOPS_AWS_ROLE_ARN` to the role, then delete
   `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. Each function exchanges its
   short-lived OIDC token (from the `x-vercel-oidc-token` header) with
   `sts:AssumeRoleWithWebIdentity`; credentials last one hour and are cached.
2. **AssumeRole with an ExternalId.** Keep a base identity that may only call
   `sts:AssumeRole`, set `CLOUDOPS_AWS_ROLE_ARN` and `CLOUDOPS_AWS_EXTERNAL_ID`,
   and use `trust-policy-assume-role.json` on the role.
3. **Default chain** (unchanged behaviour) when no role is set.

`CLOUDOPS_AWS_AUTH` can force `default`, `assume_role` or `oidc`; the default
`auto` picks OIDC when a token is present. Operators can check which mode is
active, and whether long-lived keys are in use, at `GET /api/security/status`
or on the console's Security page. STS calls are free.
