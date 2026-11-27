# The two Vercel projects CloudOps AI runs on, plus the API's non-secret
# configuration. Both projects already exist: import them before the first
# apply (see infra/terraform/README.md) so Terraform adopts them instead of
# trying to create duplicates.
#
# Secrets stay out of Terraform on purpose: DATABASE_URL, session secrets and
# any AI provider keys are set in the Vercel dashboard, so they never land in
# state. The API uses OIDC federation, so there are no AWS keys to manage.
#
# Hobby-plan friendly: nothing here needs a paid Vercel feature.

locals {
  git = var.github_repo == null ? null : {
    type              = "github"
    repo              = var.github_repo
    production_branch = var.production_branch
  }

  api_settings = merge(
    {
      CLOUDOPS_AI_CORS_ORIGINS = join(",", var.web_origins)
      CLOUDOPS_DEMO_ENABLED    = var.demo_enabled ? "true" : "false"
      AWS_REGION               = var.aws_region
    },
    var.aws_role_arn == null ? {} : {
      CLOUDOPS_AWS_ROLE_ARN = var.aws_role_arn
      CLOUDOPS_AWS_AUTH     = "oidc"
    },
  )
}

resource "vercel_project" "web" {
  name             = var.web_project_name
  framework        = "vite"
  root_directory   = "frontend"
  install_command  = "npm install"
  build_command    = "npm run build"
  output_directory = "dist"
  git_repository   = local.git
}

resource "vercel_project" "api" {
  name           = var.api_project_name
  root_directory = "backend"
  git_repository = local.git

  # Vercel always issues short-lived OIDC tokens now; team issuer mode makes the
  # issuer oidc.vercel.com/<team>, which is what the AWS role trusts.
  oidc_token_config = {
    issuer_mode = "team"
  }
}

resource "vercel_project_environment_variable" "api" {
  for_each = local.api_settings

  project_id = vercel_project.api.id
  key        = each.key
  value      = each.value
  target     = ["production"]
  sensitive  = false
}

resource "vercel_project_environment_variable" "operators" {
  count = length(var.operator_emails) > 0 ? 1 : 0

  project_id = vercel_project.api.id
  key        = "CLOUDOPS_OPERATOR_EMAILS"
  value      = join(",", var.operator_emails)
  target     = ["production"]
  sensitive  = true
}
