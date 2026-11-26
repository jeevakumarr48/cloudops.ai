# CloudOps AI

## Overview

CloudOps AI is an AI-assisted cloud infrastructure decision and governance platform. It combines read-only AWS data, CloudWatch metrics, Cost Explorer, Terraform plans, Infracost, deterministic rules, and an explanation layer in a single dashboard.

## Problem Statement

Cloud infrastructure decisions span operational data, cost impact, utilization, policy, and infrastructure-as-code changes. Teams need a concise, auditable way to review those signals without handing infrastructure control to an automated system.

## Solution

CloudOps AI discovers EC2 resources, reads available utilization and cost data, detects optimization and governance findings, and presents evidence and recommendations for human review. It does not create, modify, terminate, or apply AWS or Terraform resources.

## Architecture

```text
AWS EC2 + CloudWatch + Cost Explorer
                 |
             FastAPI API
                 |
       Deterministic decision engine
                 |
          AI explanation layer
                 |
          React/Vite dashboard
```

## How It Works

1. The backend reads AWS resources, metrics, and billing data through boto3.
2. The decision engine evaluates structured data with deterministic rules.
3. The AI layer explains findings, context, trade-offs, and risk; it does not make or execute infrastructure decisions.
4. Terraform plan and Infracost payloads can be submitted to the read-only IaC analysis endpoint for cost-aware human review.

## Technology Stack

- React, Vite, Axios, Recharts, and Lucide React
- FastAPI, Uvicorn, boto3, and pytest
- Terraform plan JSON and Infracost v2.16.3-shaped scan data
- GitHub Actions for backend tests and frontend lint/build validation

## AWS Integration

The backend uses read APIs for EC2 discovery, CloudWatch CPU metrics, and Cost Explorer. Credentials come from the standard boto3 chain: environment variables, shared AWS configuration, or an attached IAM role. No credentials are stored in the repository.

## Terraform + Infracost Workflow

Terraform is used for plan, cost analysis, and demonstration only:

```bash
terraform plan -out tfplan
terraform show -json tfplan > plan.json
infracost breakdown --path . --format json --out-file infracost.json
```

The API accepts a Terraform plan, metrics list, and real Infracost JSON at `POST /api/iac/analyze`. The endpoint normalizes real project/resource data, preserves reported currency and costs, and never runs `terraform apply`.

## Decision Engine

The deterministic engine detects findings such as stopped instances, missing ownership tags, underutilization, high-cost underutilization, and capacity changes in Terraform plans. Missing AWS metrics are treated as unavailable, never as fabricated zero values.

## AI Explanation Layer

The AI layer receives deterministic findings and produces explanations. When no AI provider is configured, the backend uses its deterministic fallback. AI has no AWS mutation tools and cannot approve or apply changes.

## Dashboard

The React dashboard provides Overview, Resources, Cost Analysis, AI Insights,
IaC Review, Governance, and Settings views. It calls the FastAPI endpoints for
real account data and renders loading, unavailable, and empty states when a
service or permission is not available. It never fabricates cloud metrics,
costs, resources, or savings.

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Service banner |
| GET | `/health` | Health check |
| GET | `/api/resources/ec2` | EC2 inventory |
| GET | `/api/metrics/ec2` | CloudWatch CPU metrics |
| GET | `/api/costs` | Cost Explorer summary |
| GET | `/api/insights` | Decision findings and explanations |
| GET | `/api/overview` | Dashboard summary |
| GET | `/api/recommendations` | Backward-compatible recommendation response |
| POST | `/api/iac/analyze` | Terraform plan and Infracost analysis |

Unavailable AWS services return structured unavailable responses. The dashboard shows unavailable states instead of inventing metrics or costs.

## Project Structure

```text
backend/                 FastAPI application and tests
backend/services/        AWS, cost, metrics, IaC, rules, and AI services
frontend/                React/Vite dashboard
infrastructure/          Terraform source and real analysis artifacts
.github/workflows/       Read-only CI checks
```

## Local Setup

Requirements: Python 3.12+, Node.js 22+, npm, and optional read-only AWS credentials.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt

cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Copy `backend/.env.example` and `frontend/.env.example` to local environment files as needed. Environment files containing secrets are ignored by Git.

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| AWS credential chain | For AWS data | Standard boto3 credentials and region |
| `VITE_API_URL` | No | FastAPI base URL for the browser |
| `CLOUDOPS_AI_CORS_ORIGINS` | No | Comma-separated allowed frontend origins |
| `CLOUDOPS_AI_API_KEY` or `OPENAI_API_KEY` | No | Optional AI explanation provider |
| `CLOUDOPS_AI_BASE_URL` / `CLOUDOPS_AI_MODEL` | No | Optional provider configuration |
| `INFRACOST_API_KEY` | No | Optional Infracost integration marker |
| `CLOUDOPS_COST_CACHE_SECONDS` | No | In-process Cost Explorer cache lifetime, default 86400 (each CE request costs $0.01) |
| `CLOUDOPS_COST_CDN_SECONDS` | No | Vercel CDN cache lifetime for successful cost responses, default 86400 |
| `CLOUDOPS_INVENTORY_CDN_SECONDS` | No | Vercel CDN cache lifetime for EC2, metrics, insights and overview responses, default 60 |
| `CLOUDOPS_DISCOVERY_CACHE_SECONDS` | No | In-process EC2 DescribeInstances cache, default 60; 0 disables |
| `CLOUDOPS_AI_CACHE_SECONDS` | No | Reuse an LLM explanation for unchanged findings, default 3600 |
| `DATABASE_URL` | On Vercel, for accounts | Postgres URL (Neon pooled endpoint). Locally defaults to SQLite `backend/cloudops.db` |
| `CLOUDOPS_COOKIE_SECURE` | No | `false` only for local HTTP development; default `true` |
| `CLOUDOPS_SESSION_DAYS` | No | Session lifetime, default 7 |
| `CLOUDOPS_REGISTRATION_OPEN` | No | `false` disables self-registration |
| `CLOUDOPS_OPERATOR_EMAILS` | For S3 views | Comma-separated emails allowed to see the deployment account's security findings |
| `CLOUDOPS_PUBLIC_SECURITY_FINDINGS` | No | `true` serves S3 findings anonymously (demo accounts only); default `false` |
| `CLOUDOPS_S3_CACHE_SECONDS` | No | S3 scan cache lifetime, default 900 |
| `CLOUDOPS_CE_MONTHLY_CALL_LIMIT` | No | Hard monthly cap on billed Cost Explorer requests, default 75 ($0.75) |

## S3 discovery and governance

| Endpoint | Purpose |
|---|---|
| `GET /api/resources/s3` | Every bucket with region, versioning, encryption, Block Public Access, policy status, ACL, lifecycle, logging, CloudWatch storage metrics and a governance summary |
| `GET /api/resources/s3/{bucket}/governance` | All seven S3 rule evaluations for one bucket, with evidence |

Security posture is sensitive (a list of public buckets is a map for
attackers), so these endpoints are **not public** by default: they require a
signed-in user listed in `CLOUDOPS_OPERATOR_EMAILS`. Set
`CLOUDOPS_PUBLIC_SECURITY_FINDINGS=true` only for a demo account whose buckets
are safe to show. Responses are never CDN-cached.

Add `?refresh=true` to rescan (honoured at most once a minute). Results are
cached for 15 minutes (`CLOUDOPS_S3_CACHE_SECONDS`).

Each check reports `ok`, `not_configured`, `access_denied` or `error`. Each rule
returns one evidence state: `CONFIRMED`, `POTENTIAL`, `INSUFFICIENT_EVIDENCE`,
`NO_ISSUE` or `DATA_UNAVAILABLE`. Storage size comes only from CloudWatch's
daily `BucketSizeBytes`; a missing datapoint is `null`, never zero. No S3 rule
estimates savings.

| Rule | Category | Raised when |
|---|---|---|
| `S3_PUBLIC_POLICY` | SECURITY | AWS reports the bucket policy is public (CRITICAL, or MEDIUM if RestrictPublicBuckets blocks it) |
| `S3_PUBLIC_ACL` | SECURITY | ACL grants AllUsers/AuthenticatedUsers (HIGH, or LOW if IgnorePublicAcls applies) |
| `S3_BLOCK_PUBLIC_ACCESS` | SECURITY | Any of the four settings is off at both bucket and account level |
| `S3_DEFAULT_ENCRYPTION` | SECURITY | No default encryption rule |
| `S3_VERSIONING` | CONFIGURATION | Versioning disabled or suspended (low confidence; depends on data) |
| `S3_LIFECYCLE` | STORAGE | No lifecycle rules and at least 1 GiB stored or versioning on; insufficient evidence when size is unknown |
| `S3_ACCESS_LOGGING` | GOVERNANCE | Server access logging disabled |

The required permissions are in [`docs/iam/cloudops-readonly-policy.json`](docs/iam/cloudops-readonly-policy.json).

## RDS discovery and governance

| Endpoint | Purpose |
|---|---|
| `GET /api/resources/rds` | DB instances with engine, class, storage, Multi-AZ, public access, encryption, backups, deletion protection, tags, internet-open security group rules, 14 days of hourly CloudWatch metrics and a governance summary |
| `GET /api/resources/rds/{database_id}/governance` | All eight RDS rule evaluations for one database, with evidence |

Optional `?region=` (default region otherwise) and `?refresh=true` (once a
minute). Same access rule as S3: operator sign-in unless
`CLOUDOPS_PUBLIC_SECURITY_FINDINGS=true`.

| Rule | Category | Raised when |
|---|---|---|
| `RDS_PUBLIC_ACCESS` | SECURITY | Publicly accessible: CRITICAL if a security group allows 0.0.0.0/0 or ::/0 on the DB port, HIGH if groups are unreadable, MEDIUM if they are closed |
| `RDS_STORAGE_ENCRYPTION` | SECURITY | Storage not encrypted |
| `RDS_BACKUP_RETENTION` | AVAILABILITY | Retention 0 days (HIGH) or under 7 days |
| `RDS_MULTI_AZ` | AVAILABILITY | Production-tagged and single-AZ; insufficient evidence when untagged or Aurora |
| `RDS_DELETION_PROTECTION` | GOVERNANCE | Off on a production or untagged database |
| `RDS_LOW_UTILIZATION` | UTILIZATION | 14 days with at least 80% hourly coverage and CPU mean < 10%, p95 < 20%, peak < 40%. Production databases get LOW severity, low confidence and a review-only recommendation |
| `RDS_STORAGE_HEADROOM` | STORAGE | Free storage under 10% (or 20% without autoscaling), or over 80% unused on 100+ GiB |
| `RDS_GP2_STORAGE` | COST | gp2 storage; gp3 is usually cheaper per GB, difference not calculated |

Utilization is never judged on partial history, stopped instances or missing
metrics; those return `INSUFFICIENT_EVIDENCE` or `DATA_UNAVAILABLE`.

## Unified governance engine

One engine runs every deterministic rule across EC2, S3, RDS and Cost
Explorer, scores the findings and tracks their lifecycle.

| Endpoint | Purpose |
|---|---|
| `GET /api/governance/findings` | Active findings sorted by priority. Filters: `category`, `severity`, `evidence_state`, `resource_type`, `status`, `include_resolved` |
| `GET /api/governance/summary` | Counts by severity, category, resource type, evidence state and status, top 5 priorities, per-source status and the scoring formula |
| `PATCH /api/governance/findings/{finding_id}` | Set `open`, `acknowledged`, `accepted_risk` or `false_positive` with a note (signed-in operator only; audited) |
| `POST /api/governance/iac` | Terraform plan + optional metrics/Infracost as unified, scored findings (same input as `/api/iac/analyze`) |

The original `/api/insights` and `/api/recommendations` are unchanged.

**Every finding** carries `finding_id` (stable hash of resource type, rule and
resource), `rule_id`, `resource_type`, `resource_id`, `region`, `category`,
`severity` (CRITICAL to INFO), `evidence_state`, `title`, `description`, cited
`evidence`, `detection_source`, `recommendation`, `remediation_steps`,
`confidence`, `missing_information`, `requires_human_approval` (always true),
`priority` and `lifecycle` (`status`, `first_detected`, `last_detected`,
`resolved_at`, `times_reopened`).

**Lifecycle.** Findings are stored in the `governance_findings` table. When a
source scans successfully and a finding is no longer detected, it is resolved
automatically; if it comes back it reopens. A source that fails leaves its
findings untouched, so an outage never resolves anything.

**Priority score** (0 to 100, deterministic; the AI layer never changes it):

```
impact   = 0.45*S + 0.30*X + 0.25*F
priority = max(0, impact*C - P_effort - P_risk)
```

| Input | Values |
|---|---|
| S severity | CRITICAL 100, HIGH 75, MEDIUM 50, LOW 25, INFO 0 |
| X exposure | 100 confirmed internet exposure (critical/high), 60 potential, else 0 |
| F financial | 0 unless AWS or Infracost measured a dollar figure, then min(100, 20 x log2(1 + USD)) |
| C confidence | CONFIRMED 1.0, POTENTIAL 0.7, INSUFFICIENT_EVIDENCE 0.3 |
| P_effort, P_risk | low 0, medium 5, high 10 per rule; resizing a production resource is high risk |

New rules in this phase: `EC2_OPEN_ADMIN_PORTS` (SSH/RDP open to the internet
on a public instance), `EC2_STOPPED_INSTANCE`, `EC2_LOW_UTILIZATION` (14 days,
80% coverage, mean < 10% and peak < 40%), `EC2_MISSING_OWNER_TAG`,
`EC2_MISSING_ENVIRONMENT_TAG` and `COST_WEEKLY_INCREASE` (last 7 complete days
vs the 7 before: +25% and +$1 is MEDIUM, +100% and +$5 is HIGH). The cost rule
reuses the per-day series now included in `/api/costs?period=daily` (`daily`
field), so it makes no extra billed request.

After pulling this change, run `alembic upgrade head` again on production.

## Accounts, workspaces and the database

The original dashboard endpoints stay public and read-only. Accounts and
workspaces are additive:

| Endpoint | Purpose |
|---|---|
| `POST /api/auth/register` | Create an account and a personal workspace (you are its admin) |
| `POST /api/auth/login` / `POST /api/auth/logout` | Start or end a session (HttpOnly, SameSite=Lax cookie) |
| `GET /api/auth/me` | Current user and workspace memberships |
| `GET /api/workspaces`, `POST /api/workspaces` | List or create workspaces |
| `GET /api/workspaces/{id}` | Workspace and members (members only) |
| `POST /api/workspaces/{id}/members` | Add a registered user as `admin` or `viewer` (admins only) |
| `GET /api/workspaces/{id}/audit` | Recent audit events (admins only) |

Passwords are hashed with Argon2id; session tokens are stored only as SHA-256
digests. Non-members receive 404 for another workspace. Login and registration
are rate limited in the database.

Locally nothing needs configuring: a SQLite file is created and migrated on
first use. In production set `DATABASE_URL` and migrate explicitly:

```bash
cd backend
DATABASE_URL="postgresql://..." alembic upgrade head
```

Cost Explorer results are also stored in the database so every serverless
instance shares them, and billed requests are capped per month
(`CLOUDOPS_CE_MONTHLY_CALL_LIMIT`). When the cap is reached the most recent real
snapshot is served; nothing is estimated.

## Testing

```bash
python -m pytest backend/tests -q
cd frontend
npm run lint
npm run build
```

The backend tests use mocked structured data and do not create AWS resources.

## Deployment

Deploy the services separately. Start the backend with:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Set `CLOUDOPS_AI_CORS_ORIGINS` to the deployed frontend origin and set the frontend build variable `VITE_API_URL` to the deployed backend URL. The frontend is a static Vite build (`npm run build`, output in `frontend/dist`). No deployment step runs Terraform or changes AWS infrastructure.

## Security

Never commit `.env` files, AWS keys, Terraform state, plan files, or provider secrets. Use least-privilege read-only AWS permissions for demonstrations. The backend CORS allowlist is configurable, and API error responses avoid returning credentials or provider responses.

## Limitations

The current release supports EC2 discovery, CloudWatch CPU metrics, Cost
Explorer, Terraform plan review, and Infracost normalization. It does not apply
Terraform changes, mutate AWS resources, persist review history, or implement
additional AWS services such as S3, RDS, or Kubernetes.

## Future Scope

Potential extensions include richer multi-resource inventory, persisted review history, additional cloud providers, and authenticated team workflows. These are intentionally outside the current read-only scope.
