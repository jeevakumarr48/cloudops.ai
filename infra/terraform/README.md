# Terraform for CloudOps AI's own platform

CloudOps AI governs other people's infrastructure, so its own access is managed
as code too. Two small roots, applied separately:

| Root | Manages | Cost |
| --- | --- | --- |
| [`aws/`](aws) | Vercel OIDC identity provider, the read-only role, its policy | $0: IAM and STS are free |
| [`vercel/`](vercel) | The console and API projects, OIDC issuer mode, the API's non-secret settings | $0 on the Hobby plan |

Nothing here creates compute, storage, networking or anything else billable.

## What it guarantees

- **Read-only by construction.** The role's permissions are loaded from
  [`docs/iam/cloudops-readonly-policy.json`](../../docs/iam/cloudops-readonly-policy.json),
  the same file the docs describe. A precondition rejects any action that is not
  `Describe*`, `Get*` or `List*`, any wildcard, and reads of object contents or
  secrets (`s3:GetObject`, `secretsmanager:GetSecretValue`, `kms:Decrypt`, …).
  The plan fails before anything reaches AWS.
- **No AWS keys anywhere.** The role trusts Vercel's OIDC issuer
  (`oidc.vercel.com/<team>`), pinned to the API project's production
  environment by `sub`, not just the audience. Preview deployments get no
  AWS access unless you list them.
- **No secrets in state.** `DATABASE_URL`, session secrets and AI keys stay in
  the Vercel dashboard. Terraform only manages settings like the role ARN and
  CORS origins; operator emails are marked sensitive. The Vercel token is read
  from `VERCEL_API_TOKEN`, never a file.

## Tests

`terraform test` runs with mocked providers: no credentials, no network to AWS
or Vercel, nothing created. CI runs format, validate and test on every push.

```bash
make tf-check   # or, per root:
terraform -chdir=infra/terraform/aws init -backend=false && terraform -chdir=infra/terraform/aws test
```

The AWS suite checks the subject pinning, the ExternalId path, reuse of an
existing OIDC provider, input validation, and that a policy containing
`ec2:TerminateInstances` or `s3:GetObject` fails the plan.

## Applying (you run this, CI never does)

State is local by default: these roots hold no secrets, and a remote S3
backend would add a (small) bill. Keep `terraform.tfstate` out of git (it is
ignored).

```bash
# 1. AWS: credentials for an admin in the target account
cd infra/terraform/aws
cp terraform.tfvars.example terraform.tfvars   # set vercel_team_slug
terraform init
terraform plan -out tfplan                     # review: 3–4 IAM resources, nothing else
terraform apply tfplan
terraform output -raw role_arn

# 2. Vercel: both projects already exist, so adopt them first
cd ../vercel
export VERCEL_API_TOKEN=...                    # Account Settings → Tokens
cp terraform.tfvars.example terraform.tfvars   # set team, aws_role_arn, origins
terraform init
terraform import vercel_project.web <team_id>/<web_project_id>
terraform import vercel_project.api <team_id>/<api_project_id>
terraform plan                                 # read the diff before applying
```

Read the Vercel plan carefully: on imported projects it shows every setting
that differs from this code. Change the code to match anything you want to
keep, then apply. Existing environment variables with the same key must be
imported too (`terraform import 'vercel_project_environment_variable.api["AWS_REGION"]' <team_id>/<project_id>/<env_id>`)
or removed in the dashboard first.

After the role is live, delete `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
from the API project. The console's Security page shows `oidc` mode and no
long-lived keys once it works.

## Already have an OIDC provider?

An account can hold one provider per issuer URL. If `oidc.vercel.com/<team>`
exists already, set `create_oidc_provider = false` and pass its ARN as
`existing_oidc_provider_arn`, or import it:
`terraform import 'aws_iam_openid_connect_provider.vercel[0]' <arn>`.
