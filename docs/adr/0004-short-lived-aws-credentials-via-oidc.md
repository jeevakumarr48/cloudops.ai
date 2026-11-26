# 0004. Short-lived AWS credentials through Vercel OIDC

- Status: Accepted
- Date: 2026-11-26 (recorded)

## Context

The API runs on Vercel. The simplest setup is an IAM user's access key in an
environment variable: a long-lived secret that works from anywhere if it leaks
and has to be rotated by hand.

## Decision

`core/aws_session.py` supports three modes, chosen by `CLOUDOPS_AWS_AUTH`
(`auto` by default):

1. **OIDC (preferred).** Each function exchanges its Vercel OIDC token for one-hour
   credentials with `sts:AssumeRoleWithWebIdentity`. The role's trust is pinned
   by `sub` to the API project's production environment, not just the audience.
2. **AssumeRole with an ExternalId**, for hosts without OIDC.
3. **The default boto3 chain**, for local development.

The Security page and `GET /api/security/status` show which mode is active and
whether long-lived keys are present. The role, provider and trust are
Terraform (`infra/terraform/aws`). Workspaces register a role ARN and
ExternalId, never keys.

## Consequences

- No AWS secret exists in Vercel, the repo or the database once OIDC is on.
- Preview deployments get no AWS access unless explicitly listed.
- Local development still needs a profile; the docs say to use a read-only one.
