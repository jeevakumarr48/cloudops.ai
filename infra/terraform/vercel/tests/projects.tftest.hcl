# Runs with `terraform test`. The Vercel provider is mocked: no token, no
# network, nothing created.

mock_provider "vercel" {}

variables {
  team = "acme"
}

run "api_project_uses_team_oidc" {
  command = plan

  assert {
    condition     = vercel_project.api.oidc_token_config.issuer_mode == "team"
    error_message = "The API must issue team-mode OIDC tokens so AWS can pin the trust to it."
  }

  assert {
    condition     = vercel_project.api.root_directory == "backend" && vercel_project.web.root_directory == "frontend"
    error_message = "Each project builds from its own folder of the monorepo."
  }
}

run "no_role_means_no_aws_settings" {
  command = plan

  assert {
    condition     = !contains(output.api_settings, "CLOUDOPS_AWS_ROLE_ARN")
    error_message = "Without a role ARN the variable is not managed."
  }
}

run "role_switches_the_api_to_oidc" {
  command = plan

  variables {
    aws_role_arn = "arn:aws:iam::123456789012:role/cloudops-ai-readonly"
  }

  assert {
    condition     = vercel_project_environment_variable.api["CLOUDOPS_AWS_AUTH"].value == "oidc"
    error_message = "Setting a role must force OIDC federation."
  }

  assert {
    condition     = alltrue([for v in vercel_project_environment_variable.api : v.target == toset(["production"])])
    error_message = "Settings apply to production only."
  }
}

run "settings_never_include_secrets" {
  command = plan

  variables {
    aws_role_arn    = "arn:aws:iam::123456789012:role/cloudops-ai-readonly"
    operator_emails = ["ops@example.com"]
  }

  assert {
    condition     = length([for k in output.api_settings : k if can(regex("(?i)(SECRET|PASSWORD|TOKEN|DATABASE_URL|ACCESS_KEY|API_KEY)", k))]) == 0
    error_message = "Secrets are set in the Vercel dashboard, never through Terraform."
  }

  assert {
    condition     = vercel_project_environment_variable.operators[0].sensitive
    error_message = "Operator emails are stored as a sensitive variable."
  }
}

run "wildcard_origins_are_rejected" {
  command = plan

  variables {
    web_origins = ["https://*.vercel.app"]
  }

  expect_failures = [var.web_origins]
}
