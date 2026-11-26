# 0001. Read-only and recommendation-only

- Status: Accepted
- Date: 2026-11-26 (recorded)

## Context

A governance tool that can act on what it finds is one bug, one prompt
injection or one stolen credential away from deleting a database. The people
who would connect an account to it need to be able to say, from the IAM policy
alone, what it can and cannot do.

## Decision

CloudOps AI never changes cloud resources. The IAM policy contains only
`Describe`, `Get` and `List` actions, with no wildcards and no reads of object
contents (`s3:GetObject` is absent). Findings become recommendations, fix
commands are text for a human to copy, and every recommendation is marked
*human approval required*. The Terraform for the role fails the plan if a
non-read action is ever added (`infra/terraform/aws/main.tf`).

## Consequences

- The blast radius of a compromise is disclosure of configuration metadata,
  not change or deletion.
- An auditor can verify the claim from one 17-action policy file.
- Users do the last step themselves. Fix commands are labelled `read_only`,
  `safe`, `disruptive` or `destructive`, with an undo step, to make that step
  quick and safe.
- Features like auto-remediation are ruled out unless this decision is
  superseded.

## Alternatives considered

- **Optional write mode behind a flag.** Rejected: a flag is one misconfiguration
  from production, and it would change what the policy has to allow.
- **Use `ReadOnlyAccess` managed policy.** Rejected: it includes reads of data
  (`s3:GetObject`, `dynamodb:GetItem`), not just configuration.
