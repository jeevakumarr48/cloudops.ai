# 0003. Evidence states instead of pass/fail

- Status: Accepted
- Date: 2026-11-26 (recorded)

## Context

Read-only access is often partial. If `s3:GetBucketPolicyStatus` is denied, a
pass/fail checker either reports "not public" (false reassurance) or "public"
(a fabricated finding). Missing CloudWatch datapoints are often read as 0% CPU
and become a bogus "underutilized" finding.

## Decision

Every finding has an evidence state: `CONFIRMED` (AWS data directly shows it),
`POTENTIAL` (likely, needs confirmation) or `INSUFFICIENT_EVIDENCE`. Checks that
could not run report `DATA_UNAVAILABLE` and name the permission to grant.
Missing metrics stay missing, never zero. Confidence multiplies the priority
score (1.0, 0.7, 0.3), so uncertain findings rank lower but stay visible.
Each source (EC2, S3, RDS, cost) reports its own status, so one failure never
hides the others.

## Consequences

- No fabricated findings and no false "all clear".
- The UI needs more states (scanned, unavailable, access denied, need more
  data), and every page has to render them.
- Fix commands and the fix-first plan skip `INSUFFICIENT_EVIDENCE` findings.
