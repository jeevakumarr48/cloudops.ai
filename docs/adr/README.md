# Architecture decision records

Short records of the decisions that shape CloudOps AI: the context, what was
chosen, and what it costs. Format: [Michael Nygard's ADR template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
They were written down on 2026-11-26, after the decisions were made, from the
code and commit history.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-read-only-recommendation-only.md) | Read-only and recommendation-only | Accepted |
| [0002](0002-rules-detect-model-explains.md) | Deterministic rules detect; a model may only rewrite, behind a validator | Accepted |
| [0003](0003-evidence-states-not-booleans.md) | Evidence states instead of pass/fail | Accepted |
| [0004](0004-short-lived-aws-credentials-via-oidc.md) | Short-lived AWS credentials through Vercel OIDC | Accepted |
| [0005](0005-server-sessions-not-jwt.md) | Server-side sessions in a first-party cookie, not JWTs | Accepted |
| [0006](0006-postgres-as-the-only-stateful-dependency.md) | Postgres for cache, budgets and rate limits; no Redis | Accepted |
| [0007](0007-serverless-hosting-at-zero-cost.md) | Serverless hosting with a $0 target and a $1 ceiling | Accepted |
| [0008](0008-demo-runs-sample-data-through-real-rules.md) | The public demo runs sample inputs through the real rules | Accepted |

New decisions get the next number. A reversed decision keeps its file and is
marked *Superseded by 00NN*.
