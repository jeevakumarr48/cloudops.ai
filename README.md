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
