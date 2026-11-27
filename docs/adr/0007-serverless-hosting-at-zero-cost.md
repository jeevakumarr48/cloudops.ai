# 0007. Serverless hosting with a $0 target and a $1 ceiling

- Status: Accepted
- Date: 2026-11-26 (recorded)

## Context

This is a portfolio-scale product with real AWS integration. Always-on compute
(EC2, RDS, a load balancer, a NAT gateway) would cost more per month than the
product is worth, and free tiers end.

## Decision

- Console: static Vite build on Vercel.
- API: FastAPI as a Vercel Python function (`backend/vercel.json`, 60 s max).
- Database: Neon Postgres free tier.
- AWS footprint: one IAM role, one policy and one OIDC provider, all free.
- Billed AWS calls are capped in code: Cost Explorer calls are budgeted and
  cached, model calls are off by default and capped.
- The same API runs in Docker (`docker compose up`) for local work and CI, so
  the app is not tied to Vercel.

## Consequences

- Running cost is $0 at portfolio traffic; the caps keep the worst case near $1.
- Cold starts add latency to the first request; scans are cached for 60 s.
- Long scans are bounded by the function timeout.
- Free-tier terms can change. The release checklist (`docs/RELEASE.md`) says to
  re-check pricing instead of assuming it is permanent.
