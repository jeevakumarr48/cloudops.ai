# CloudOps AI architecture

CloudOps AI is a read-only governance and decision-support system. It turns AWS
configuration, metrics, cost data and Terraform plans into scored findings with
cited evidence, explains them, and leaves every change to a human. The reasons
behind the design are in [the decision records](adr/README.md); the security
view is in [the threat model](threat-model.md).

## System context

```mermaid
flowchart LR
    visitor([Visitor]) -->|public demo, sample data| web
    operator([Operator]) -->|signed in| web
    web[React console<br/>Vercel static site] -->|/api rewrite, same origin| api[FastAPI API<br/>Vercel Python function]
    api --> db[(Neon Postgres<br/>SQLite locally)]
    api -->|AssumeRoleWithWebIdentity<br/>Vercel OIDC token| sts[AWS STS]
    api -->|read-only Describe / Get / List| aws[EC2 · CloudWatch · S3 · RDS · Cost Explorer]
    api -.->|optional, grounded rewrite only| llm[OpenAI-compatible API or Ollama]
    ci[GitHub Actions] -.->|lint, types, tests, e2e,<br/>Docker, Terraform test| repo[(GitHub repo)]
```

Nothing in the picture can change the AWS account. The role holds only read
actions ([ADR 0001](adr/0001-read-only-recommendation-only.md)), and the model
sees finding bundles, never credentials, raw AWS responses or tools.

## Components

```mermaid
flowchart TB
    subgraph Frontend [frontend/src]
        pages[pages: Overview, Resources, Cost, AI Insights,<br/>IaC Review, Governance, Recommendations,<br/>Security, Operations, Settings]
        apijs[api.js: axios clients,<br/>demo endpoint switch]
        demo[demo/demoMode.js]
    end

    subgraph API [backend]
        mw[core/http_security.py<br/>origin check, headers, request ids]
        routers[routers: auth, workspaces, governance,<br/>ai, security, demo, ops + legacy routes in main.py]
        authz[core/authz.py<br/>operator and workspace roles]
        engine[services/governance_engine.py<br/>collect, score, persist]
        rules[ec2 / s3 / rds / cost / iac governance<br/>21 deterministic rules]
        recs[services/recommendations<br/>templates, validator, providers,<br/>fix commands, fix-first plan]
        stores[cost_store, snapshots,<br/>usage counters, scan runs]
        obs[core/observability.py<br/>JSON logs, request stats]
        awss[core/aws_session.py<br/>OIDC, AssumeRole, default chain]
    end

    pages --> apijs --> mw --> routers
    demo --> apijs
    routers --> authz
    routers --> engine --> rules
    engine --> awss
    routers --> recs
    engine --> stores
    recs --> stores
    mw --> obs
```

| Layer | Responsibility | Key files |
| --- | --- | --- |
| HTTP | Origin check on state-changing requests, security headers, request id, timing | `core/http_security.py` |
| Identity | Argon2id passwords, SHA-256-hashed session tokens, rate limits, audit events | `core/security.py`, `routers/auth.py` |
| Authorization | Operators for the deployment's own account, roles inside workspaces | `core/authz.py` |
| Collection | One scan per source (EC2, S3, RDS, cost), each isolated so one failure cannot hide the others | `services/governance_engine.py` |
| Detection | 21 rules that emit findings with evidence and an evidence state | `services/*_governance.py` |
| Scoring | `max(0, (0.45·S + 0.30·X + 0.25·F)·C − P_effort − P_risk)`, every input returned | `governance_engine.score` |
| Recommendations | Rule templates, optional model rewrite, validator, fix commands, fix-first plan | `services/recommendations/` |
| Persistence | Users, workspaces, findings and lifecycle, recommendations, feedback, snapshots, usage counters, scan runs, audit events | `core/models.py`, `migrations/` |
| Operations | Readiness, budgets, scan history, latency | `routers/ops.py`, `core/observability.py` |

## A scan, end to end

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as API
    participant S as STS
    participant W as AWS read APIs
    participant D as Database
    participant M as Model (optional)

    B->>A: GET /api/governance/findings (session cookie)
    A->>A: origin and operator checks
    A->>S: AssumeRoleWithWebIdentity (Vercel OIDC token)
    S-->>A: one-hour credentials (cached)
    par each source isolated
        A->>W: ec2:Describe*, cloudwatch:GetMetricData
        A->>W: s3:GetBucket* (configuration only, never objects)
        A->>W: rds:DescribeDBInstances
        A->>D: cached Cost Explorer result (budgeted)
    end
    A->>A: rules, evidence states, scores
    A->>D: upsert findings (lifecycle kept), record scan run
    A-->>B: findings, per-source status, summary
    B->>A: POST /api/ai/analyze (operator, rate-limited)
    A->>D: reuse the stored rewrite if the evidence hash is unchanged
    A->>M: finding bundle only
    M-->>A: JSON rewrite
    A->>A: validator: cited evidence only, no new figures,<br/>no savings claims, no destructive advice
    A-->>B: accepted rewrite, or the rule template plus the reasons
```

Missing data is never treated as a pass or a zero. A permission error makes a
rule report `DATA_UNAVAILABLE` or `INSUFFICIENT_EVIDENCE` and name the action
to grant, and the source shows as unavailable
([ADR 0003](adr/0003-evidence-states-not-booleans.md)).

## Deployment

```mermaid
flowchart LR
    subgraph Vercel
        webp[cloudops-ai<br/>static Vite build]
        apip[cloudops-ai-api<br/>Python function, team OIDC issuer]
    end
    subgraph AWS [AWS account, IAM only]
        oidc[OIDC provider<br/>oidc.vercel.com/team]
        role[cloudops-ai-readonly<br/>trust pinned to the API project, production]
    end
    neon[(Neon Postgres)]
    browser([Browser]) --> webp
    webp -->|rewrite /api and /health| apip
    apip --> neon
    apip -->|web identity| oidc --> role
```

The two projects and the IAM pieces are Terraform in
[`infra/terraform`](../infra/terraform/README.md); CI tests it with mocked
providers and never applies. Locally, `docker compose up` runs the same API on
Postgres behind nginx ([ADR 0007](adr/0007-serverless-hosting-at-zero-cost.md)).

## Data model

```mermaid
erDiagram
    USER ||--o{ USER_SESSION : has
    USER ||--o{ WORKSPACE_MEMBER : joins
    WORKSPACE ||--o{ WORKSPACE_MEMBER : has
    WORKSPACE ||--o{ CLOUD_ACCOUNT : registers
    WORKSPACE ||--o{ SNAPSHOT : caches
    WORKSPACE ||--o{ GOVERNANCE_FINDING : owns
    WORKSPACE ||--o{ AUDIT_EVENT : records
    WORKSPACE ||--o{ SCAN_RUN : records
    GOVERNANCE_FINDING ||--o| RECOMMENDATION_RECORD : "explained by (scope, finding_id)"
    RECOMMENDATION_RECORD ||--o{ RECOMMENDATION_FEEDBACK : receives
```

Rows with no workspace belong to the deployment's own AWS account (the
`global` scope). `usage_counters` stands alone: fixed-window counters for
budgets and rate limits, so no Redis is needed. A cloud account stores only a
role ARN and ExternalId, never keys.

## Cost controls

| Spend | Control |
| --- | --- |
| Cost Explorer ($0.01 per call) | Database cache shared by all instances; monthly cap `CLOUDOPS_CE_MONTHLY_CALL_LIMIT` (default 75) |
| Model calls | Off by default; operator-only, 10 per user per hour, `CLOUDOPS_AI_DAILY_CALL_LIMIT` (default 20), stored per evidence hash so a refresh never calls again |
| CloudWatch, S3 GET-class requests | Scan cache (60 s) and discovery caches; the public demo never touches AWS |
| Hosting | Vercel Hobby, Neon free tier, IAM and STS are free; no always-on compute |

The Operations page shows each budget's use for the current period.
