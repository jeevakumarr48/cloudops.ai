# CloudOps AI Architecture

CloudOps AI is a read-only decision-support system. It connects infrastructure
change context with operational and financial evidence, then leaves the final
decision with a human reviewer.

## End-to-End Flow

```text
Engineer
   |
Terraform configuration
   |
Terraform plan JSON
   |
Infracost cost impact
   +-------------------- AWS operational signals
   |                    - EC2 inventory
   |                    - CloudWatch CPU metrics
   |                    - Cost Explorer totals and service groups
   v
Deterministic decision engine
   |
Structured findings and evidence
   |
AI explanation layer
   |
React dashboard
   |
Human review
```

## Responsibilities

### Terraform

Terraform describes the demonstration infrastructure and its intended state.
The repository includes the Terraform source and provider lock file. The
application does not execute Terraform mutations.

### Terraform Plan

A plan is the proposed change input to the IaC review workflow. The backend
parses plan JSON into resource addresses, actions, before values, and after
values. Plan parsing is read-only.

### Infracost

Infracost estimates the monthly cost impact of a proposed plan. The normalizer
accepts the real v2.16.3 project/resource structure, preserves reported
currency, resource metadata, tags, support status, subresources, and component
costs, and never invents missing values.

### CloudWatch

CloudWatch supplies EC2 CPU utilization when permissions and datapoints are
available. Missing metrics remain unavailable; the decision engine does not
interpret missing data as zero utilization.

### Cost Explorer

Cost Explorer supplies the requested billing-period total and optional service
breakdown. Access failures are surfaced as an unavailable state in the API and
dashboard.

### Decision Engine

The deterministic engine owns detection. It evaluates resource state, tags,
utilization, cost, and Terraform change context to produce structured findings
with severity, evidence, and recommendations.

### AI

The AI layer explains existing findings and their trade-offs. It does not
detect independently, approve changes, call AWS mutation APIs, terminate
resources, resize instances, or run `terraform apply`. A deterministic fallback
is used when no provider key is configured.

## Deployment Boundary

The FastAPI backend and Vite frontend deploy separately. The browser receives
only the configured public API URL; AWS and AI credentials remain backend-side.
`CLOUDOPS_AI_CORS_ORIGINS` limits which frontend origins may call the API.