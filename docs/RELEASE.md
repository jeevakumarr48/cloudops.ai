# Release runbook: governance platform (phases 1-9)

Everything on `phase-1-hardening` is additive: the original endpoints, their
response shapes, the dashboard pages, routing and environment variables are
unchanged (covered by `backend/tests/test_api_contract.py`). New features stay
dormant until their environment variables are set. Nothing changes AWS.

## 1. Before deploying (one-time, about 20 minutes)

### Database (Neon, free plan)
1. Create a Neon project (free plan: about 1 GB storage per project and 100 compute-hours a month; it suspends instead of
   billing at the limits). Copy the **pooled** connection string.
2. In the Vercel **API** project, add `DATABASE_URL` for **Preview** first.
3. Apply migrations from your laptop (PowerShell):
   ```powershell
   cd backend
   $env:DATABASE_URL = "postgresql://...pooled..."
   python -m alembic -c alembic.ini upgrade head
   python -m alembic -c alembic.ini current   # expect 0003 (head)
   ```
   Migrations only create tables (users, sessions, workspaces, snapshots,
   usage counters, audit events, findings, recommendations, feedback).

### API environment variables (Vercel API project)
| Variable | Value |
| --- | --- |
| `CLOUDOPS_OPERATOR_EMAILS` | your sign-in email (comma-separated list) |
| `CLOUDOPS_AI_CORS_ORIGINS` | must include `https://cloudops-ai-roan.vercel.app` |
| `CLOUDOPS_REGISTRATION_OPEN` | `false` after you have created your account |
| `CLOUDOPS_CE_MONTHLY_CALL_LIMIT` | leave at 75 ($0.75/month cap) |
| `CLOUDOPS_AI_PROVIDER` | leave unset (`none`); recommendations work without AI |
| `CLOUDOPS_AWS_ROLE_ARN` | optional, see `docs/iam/README.md` (removes stored keys) |

Frontend project: make sure `VITE_API_URL` is **not** set to the API's own
domain. Sign-in needs the same-origin `/api` rewrite in `frontend/vercel.json`.

### AWS permissions
Attach `docs/iam/cloudops-readonly-policy.json` to the identity the API uses.
Missing permissions are reported per check as `DATA_UNAVAILABLE`; nothing breaks.

## 2. Preview

1. Push the branch: `git push -u origin phase-1-hardening`. CI runs tests,
   the AI evaluation, the migration check, lint, build and dependency audits.
2. Vercel builds Preview deployments of both projects. The preview
   **frontend** still calls the **production** API (the rewrite in
   `frontend/vercel.json` is fixed), so test the new backend against the
   **API preview URL** directly:
   ```bash
   python scripts/smoke_test.py https://<api-preview-url> --email you@example.com
   ```
   If Vercel Deployment Protection is on for previews, the script receives
   Vercel's login page; test while signed in to Vercel in a browser
   (`/health`, `/docs`) or use a protection bypass token.
3. Create your account on the preview (`POST /api/auth/register` via `/docs`),
   then set `CLOUDOPS_REGISTRATION_OPEN=false`.

## 3. Production

1. Add `DATABASE_URL` for **Production** (same Neon database, or a separate
   Neon branch; run step 1.3 against it).
2. Open a pull request from `phase-1-hardening` to `main`, review, merge.
   Both projects deploy; the API stays backward compatible with the old
   frontend during the few seconds they differ.
3. Run the smoke test against the **frontend** URL (tests the rewrite and
   cookies as a browser sees them):
   ```bash
   python scripts/smoke_test.py https://cloudops-ai-roan.vercel.app --email you@example.com
   ```
4. Open the console: Governance, Recommendations, Security. The Security page
   shows whether long-lived AWS keys are in use.

## 4. Rollback

- Vercel **Instant Rollback** to the previous production deployment, for each
  project. No data migration is needed: the old code ignores the new tables.
- Removing `DATABASE_URL` turns the new account features off (they return
  503) while the original dashboard keeps working.

## 5. Cost guardrails (target $0, ceiling $1/month)

| Item | Guardrail | Worst case |
| --- | --- | --- |
| Cost Explorer ($0.01/request) | 24h cache, edge cache, DB-shared snapshots, hard monthly cap 75 | $0.75 |
| CloudWatch GetMetricData | 60s discovery cache, 60s shared scan, 15-min S3/RDS caches, no polling | cents |
| S3 config reads (GET-class) | 15-min cache, 60s refresh cooldown | well under $0.01 |
| AI provider | off by default; user-triggered; 10 findings per run; 20 calls/day; cached per evidence | $0 (Ollama/none) |
| Vercel Hobby, Neon Free, GitHub Actions | free tiers; Vercel and Neon pause instead of billing | $0 |
| Neon storage | daily retention job, scan history capped at 200 rows, account cap (`CLOUDOPS_MAX_USERS`) | a few MB, $0 |
| Neon compute | no polling; demo mode and `/health` never touch the DB; compute sleeps when idle; Free never bills | $0 |
| STS (role/OIDC) | free | $0 |
| IAM role, policy, OIDC provider (`infra/terraform`) | free | $0 |

Re-check these prices and free-tier terms before each release: free tiers are
not permanent, and a change can move the worst case past the $1 ceiling.

## 6. Known limitations

- The validator matches patterns; it cannot catch every subtle misstatement
  or an invented name written in plain words.
- Ollama works only when the API runs on the same machine.
- Workspace-connected AWS accounts (customer roles) are modelled in the
  database but scans still cover the deployment's own account only.
- Rate limits and caches are per process plus the database; a sudden burst
  across many cold Vercel instances can exceed the in-process caches (the
  Cost Explorer cap still holds because it is counted in the database).
