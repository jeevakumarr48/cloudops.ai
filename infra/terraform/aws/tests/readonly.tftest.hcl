# Runs with `terraform test`. The AWS provider is mocked, so no credentials,
# account or network are needed and nothing is created.

mock_provider "aws" {
  # Give the new OIDC provider a known ARN at plan time so the trust policy can
  # be inspected.
  override_during = plan

  mock_resource "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::123456789012:oidc-provider/oidc.vercel.com/acme"
    }
  }
}

variables {
  vercel_team_slug = "acme"
}

run "trust_is_pinned_to_the_api_project_in_production" {
  command = plan

  assert {
    condition     = output.allowed_subjects == ["owner:acme:project:cloudops-ai-api:environment:production"]
    error_message = "The role must only trust the API project's production environment by default."
  }

  assert {
    condition     = aws_iam_openid_connect_provider.vercel[0].url == "https://oidc.vercel.com/acme"
    error_message = "The OIDC issuer must use team issuer mode."
  }

  assert {
    condition     = aws_iam_openid_connect_provider.vercel[0].client_id_list == toset(["https://vercel.com/acme"])
    error_message = "The audience must be the team URL."
  }

  assert {
    condition     = jsondecode(aws_iam_role.readonly.assume_role_policy).Statement[0].Condition.StringEquals["oidc.vercel.com/acme:sub"] == ["owner:acme:project:cloudops-ai-api:environment:production"]
    error_message = "The trust policy must pin the subject, not just the audience."
  }

  assert {
    condition     = length(jsondecode(aws_iam_role.readonly.assume_role_policy).Statement) == 1
    error_message = "Only the OIDC path is enabled by default."
  }

  assert {
    condition     = aws_iam_role.readonly.max_session_duration == 3600
    error_message = "Sessions should last one hour."
  }
}

run "policy_comes_from_the_documented_file_and_is_read_only" {
  command = plan

  assert {
    condition     = length(output.policy_actions) == 17
    error_message = "The role's actions must match docs/iam/cloudops-readonly-policy.json."
  }

  assert {
    condition     = alltrue([for a in output.policy_actions : can(regex("^[a-z0-9-]+:(Describe|Get|List)", a))])
    error_message = "Every action must be a Describe, Get or List call."
  }

  assert {
    condition     = !contains(output.policy_actions, "s3:GetObject")
    error_message = "The app must never read object contents."
  }
}

run "previews_can_be_allowed_explicitly" {
  command = plan

  variables {
    vercel_environments = ["production", "preview"]
  }

  assert {
    condition     = length(output.allowed_subjects) == 2
    error_message = "Each allowed environment gets its own subject."
  }
}

run "existing_oidc_provider_is_reused" {
  command = plan

  variables {
    create_oidc_provider       = false
    existing_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/oidc.vercel.com/acme"
  }

  assert {
    condition     = length(aws_iam_openid_connect_provider.vercel) == 0
    error_message = "No provider is created when one already exists."
  }

  assert {
    condition     = output.oidc_provider_arn == "arn:aws:iam::123456789012:oidc-provider/oidc.vercel.com/acme"
    error_message = "The role must trust the existing provider."
  }
}

run "reusing_a_provider_needs_its_arn" {
  command = plan

  variables {
    create_oidc_provider = false
  }

  expect_failures = [var.existing_oidc_provider_arn]
}

run "external_id_path_requires_a_strong_id" {
  command = plan

  variables {
    assume_role_principal_arns = ["arn:aws:iam::123456789012:user/cloudops-base"]
    external_id                = "short"
  }

  expect_failures = [var.external_id]
}

run "external_id_path_builds_a_second_trust_statement" {
  command = plan

  variables {
    assume_role_principal_arns = ["arn:aws:iam::123456789012:user/cloudops-base"]
    external_id                = "a-long-random-external-id"
  }

  assert {
    condition     = jsondecode(aws_iam_role.readonly.assume_role_policy).Statement[1].Condition.StringEquals["sts:ExternalId"] == "a-long-random-external-id"
    error_message = "The ExternalId path adds its own statement next to the OIDC one."
  }
}

run "unknown_environment_is_rejected" {
  command = plan

  variables {
    vercel_environments = ["staging"]
  }

  expect_failures = [var.vercel_environments]
}

run "a_policy_with_a_write_action_fails_the_plan" {
  command = plan

  variables {
    policy_file = "tests/fixtures/write-policy.json"
  }

  expect_failures = [aws_iam_policy.readonly]
}

run "a_policy_that_reads_object_contents_fails_the_plan" {
  command = plan

  variables {
    policy_file = "tests/fixtures/object-read-policy.json"
  }

  expect_failures = [aws_iam_policy.readonly]
}
