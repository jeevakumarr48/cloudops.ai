# 0006. Postgres for cache, budgets and rate limits; no Redis

- Status: Accepted
- Date: 2026-11-26 (recorded)

## Context

Serverless functions share no memory. An in-process cache or counter resets on
every cold start and differs between instances, so a Cost Explorer budget kept
in memory would not cap anything. Adding Redis means another service, another
bill and another secret.

## Decision

Postgres (Neon in production, SQLite locally and in tests) holds everything
that must be shared:

- `snapshots`: cached read results, keyed by scope, kind and parameters.
- `usage_counters`: fixed-window counters for the Cost Explorer monthly cap,
  the daily model-call cap and the login, registration and analyze rate limits.
- `scan_runs`, `audit_events`, findings, recommendations and feedback.

Schema changes go through Alembic migrations (0001 to 0004), and CI checks that
the migrations match the models.

## Consequences

- Caps hold across instances and cold starts.
- One stateful dependency to back up and secure.
- Counters cost a write per request they guard. Fine at this volume; Redis is
  the upgrade path if traffic grows.
