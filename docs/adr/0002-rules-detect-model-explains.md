# 0002. Deterministic rules detect; a model may only rewrite, behind a validator

- Status: Accepted
- Date: 2026-11-26 (recorded)

## Context

Language models are good at clear explanations and bad at being reliably
right about numbers, resource ids and whether something is a breach. A
governance finding that invents a $300 saving or an ARN destroys trust in
every other finding.

## Decision

Detection is 21 deterministic rules in Python. Each finding carries evidence
(the AWS call and the observation), an evidence state and a transparent score.
Each rule has a written template, so the product is complete with no model at
all (`CLOUDOPS_AI_PROVIDER=none` is the default).

When a model is configured, it receives only the finding bundle and the
template, and may rewrite the wording. `services/recommendations/validator.py`
then rejects the rewrite if it cites evidence that does not exist, states a
figure or identifier not in the evidence, claims savings or guarantees, asserts
a breach, recommends destructive or unapproved action, or downplays severity.
A rejected rewrite falls back to the template, and the reasons are shown.

An offline evaluation (`backend/evals`, 10 scenarios with grounded and
adversarial rewrites) runs in CI.

## Consequences

- Findings are reproducible and testable; the model can never create or
  remove a finding.
- Any OpenAI-compatible endpoint or a local Ollama works, and none is required.
- The validator is conservative. It sometimes rejects acceptable text, which
  costs wording quality, never accuracy.
- Rewrites are stored per evidence hash, so a page refresh never calls the model.

## Alternatives considered

- **Model-led detection (send the inventory to the model).** Rejected: not
  reproducible, expensive per scan, and sends more account data to a third party.
- **No model at all.** Kept as the default; the rewrite is an optional layer.
