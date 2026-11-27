# 0008. The public demo runs sample inputs through the real rules

- Status: Accepted
- Date: 2026-11-26 (recorded)

## Context

Recruiters and reviewers need to see the product without an AWS account, but
the deployment's own account data must stay behind sign-in. A hand-written
mock would drift from the real engine and could show findings the rules would
never produce.

## Decision

`/api/demo/*` serves a scan built from the evaluation scenarios
(`backend/evals/scenarios.py`) run through the real rules, scoring and
recommendation code. Every response carries `demo: true` and a sample-data
notice, the console shows a permanent banner, and actions that would change
state are disabled. The demo never calls AWS or a model, is cacheable by the
CDN, and can be turned off with `CLOUDOPS_DEMO_ENABLED=false`.

## Consequences

- The demo cannot drift from the product: a rule change shows up in both.
- No real account data is public; live AWS endpoints need an operator session.
- The demo shows a fixed scan time, so it is clearly not live.
