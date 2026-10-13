# PRODUCT.md — CloudOps AI

## What it is

CloudOps AI is a read-only cloud infrastructure decision and governance
workspace. It discovers EC2 resources, reads available utilization and cost
data, detects optimization and governance findings, and presents evidence and
recommendations for human review.

## Users and jobs

- **Cloud engineers, architects, and FinOps teams** reviewing one AWS account.
  Their daily job: open the workspace and know what the account looks like right
  now, what it costs, what needs a decision, and what was never measured.
- **Evaluators** verifying the read-only claim: nothing in the product can
  create, change, or terminate AWS or Terraform resources.

## What makes it different

Decision and explanation are separated. A deterministic rule engine detects
findings from measured data; an explanation layer adds context and trade-offs.
AWS and Terraform mutations are not possible from the product. Terraform plans
and Infracost output are analyzed read-only.

## Platform and stack

- Web. React 19 + Vite SPA (frontend/) over a FastAPI backend (backend/).
- Backend must not be modified by frontend work; it defines the API contract.
- Icons: lucide-react. Charts: recharts. HTTP: axios.

## Durable constraints

- **Never fabricate data.** An unavailable measurement is an em dash with a
  reason, never an invented number, a zero, or a plausible guess.
- Missing AWS metrics, costs, resources, or savings are shown as unavailable
  states, never as fabricated values.
- Read-only promise is part of the product's identity and is stated in the
  interface.
- Currency comes from the API payload; the frontend never re-denominates.

## Terminology

- Sheet / view: the seven navigable areas (Overview, Resources, Cost Analysis,
  AI Insights, IaC Review, Governance, Settings).
- Finding: a deterministic detection with evidence, severity, and a
  recommendation, awaiting human review.
- Register / measurement: a value taken from the API, or an em dash.

## Brand commitments

- Product name: CloudOps AI. Subtitle: Cloud Intelligence Platform.
- **Pinned visual reference (2026-10):** the beehiiv dashboard
  (`beehiiv Web 193.png`). White cards on a cool near-white ground, one
  magenta-pink data accent, calm comfortable density, charts as the loudest
  element on the Overview. The reference sets the quality bar and the family
  of the world; it is not copied feature-for-feature.

## Voice

Brief, exact, engineer-to-engineer. Sentence case. Full stops, no exclamation
marks. No marketing words, no emoji, no em-dash flourishes in prose. Controls
name what happens.

## Open decisions

- No authenticated user exists in the current API, so the workspace shows no
  personal greeting or avatar; the audit log of reviews is out of current scope.
