# Changelog

All notable changes to CloudOps AI. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The public API (paths and response
fields under `/api`) is the versioned surface.

## [1.0.0] - 2026-11-26

First release as a governance platform. Everything stays read-only: no AWS
write action, no Terraform apply, no automatic change.

### Added

- **Accounts and workspaces.** Registration and sign-in with Argon2id
  passwords and server-side sessions in an `HttpOnly` first-party cookie;
  workspaces with admin and member roles; operator allowlist
  (`CLOUDOPS_OPERATOR_EMAILS`); audit log of sign-ins and status changes.
- **S3 and RDS governance.** Read-only discovery and rules for public access,
  encryption, versioning, logging, lifecycle, backups, Multi-AZ, deletion
  protection, storage type and headroom.
- **Unified governance engine.** 21 rules across EC2, S3, RDS, cost and
  Terraform plans; evidence states (`CONFIRMED`, `POTENTIAL`,
  `INSUFFICIENT_EVIDENCE`); a transparent priority score; a lifecycle kept
  across scans; per-source status so one failing service never hides the rest.
- **Recommendations.** A written template per rule, an optional rewrite by an
  OpenAI-compatible model or local Ollama, and a validator that rejects
  invented figures, identifiers, savings claims and destructive advice. Stored
  per evidence hash, so refreshing never calls the model again.
- **Fix commands and fix-first plan.** Copy-ready AWS CLI steps to record,
  change, verify and undo, labelled by impact, plus a per-resource plan.
- **Offline evaluation** of 10 scenarios with grounded and adversarial rewrites.
- **Governance console** pages: Governance, Recommendations, Security,
  Operations, plus sign-in.
- **Public demo** (`/?demo=1`) that runs sample inputs through the real rules,
  clearly labelled, with no AWS or model calls.
- **Credentials without keys.** Vercel OIDC web identity and AssumeRole with
  ExternalId; the Security page shows the active mode.
- **Observability.** JSON logs with request ids, `/health/ready`, request
  metrics with p95 latency, scan history, and the Operations page with budget use.
- **Infrastructure as code** for the app's own IAM role, OIDC trust and Vercel
  projects (`infra/terraform`), with `terraform test` suites on mocked providers.
- **Developer setup.** Docker images, `docker compose` stack on Postgres,
  `Makefile`, pre-commit hooks.
- **Quality gates in CI.** Ruff, mypy, pytest with a 90% coverage floor,
  Alembic drift check, offline evaluation, pip-audit, ESLint, Vitest,
  Playwright on desktop and phone, Terraform format/validate/test, and a Docker
  job that smoke-tests the whole stack. Dependabot for all ecosystems.
- **Docs.** Architecture diagrams, eight decision records, a STRIDE threat
  model, a case study and a release runbook.

### Changed

- Endpoints that read the deployment's AWS account (`/api/resources/*`,
  `/api/metrics/ec2`, `/api/costs*`, `/api/insights`, `/api/overview`,
  `/api/recommendations`) now require a signed-in operator and return
  `private, no-store`. Set `CLOUDOPS_PUBLIC_SECURITY_FINDINGS=true` to restore
  public access. Signed-out visitors are offered the demo.
- Errors use one envelope (`status`, `error`, `code`, `request_id`, `detail`);
  legacy fields are kept.
- Cost Explorer calls are cached in the database and capped per month
  (`CLOUDOPS_CE_MONTHLY_CALL_LIMIT`, default 75).

### Security

- Origin check on state-changing requests, rate limits on sign-in,
  registration and analysis, security headers on the API and the console
  (including a Content-Security-Policy), and a 2 MB request body limit
  (`CLOUDOPS_MAX_BODY_BYTES`).

### Upgrade notes

1. Set `DATABASE_URL` and run `alembic upgrade head` (migrations 0001 to 0004).
2. Set `CLOUDOPS_OPERATOR_EMAILS` and `CLOUDOPS_AI_CORS_ORIGINS` on the API.
3. Optionally apply `infra/terraform/aws` and switch the API to OIDC, then
   delete the AWS access keys from Vercel.
4. Follow [docs/RELEASE.md](docs/RELEASE.md) for preview, smoke test and rollback.

## 0.1.0 - 2026-10-03 (untagged)

Initial dashboard: EC2 inventory, CloudWatch CPU, Cost Explorer summary and
forecast, rule-based insights, Terraform plan and Infracost analysis, deployed
on Vercel.

[1.0.0]: https://github.com/jeevakumarr48/cloudops.ai/releases/tag/v1.0.0
