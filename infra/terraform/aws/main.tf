# The read-only identity CloudOps AI uses to scan an AWS account.
#
# Everything here is free: IAM roles, policies and OIDC providers have no charge,
# and STS calls are free. Nothing in this module creates compute, storage or
# networking. The permissions come from docs/iam/cloudops-readonly-policy.json,
# the same file the docs point to, so there is one source of truth.

locals {
  oidc_host         = "oidc.vercel.com/${var.vercel_team_slug}"
  oidc_audience     = "https://vercel.com/${var.vercel_team_slug}"
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.vercel[0].arn : var.existing_oidc_provider_arn

  # Pin the trust to one project and the chosen environments, never the whole team.
  oidc_subjects = [
    for env in var.vercel_environments :
    "owner:${var.vercel_team_slug}:project:${var.vercel_api_project_name}:environment:${env}"
  ]

  oidc_statement = {
    Sid       = "CloudOpsAIFromVercel"
    Effect    = "Allow"
    Action    = "sts:AssumeRoleWithWebIdentity"
    Principal = { Federated = local.oidc_provider_arn }
    Condition = {
      StringEquals = {
        "${local.oidc_host}:aud" = local.oidc_audience
        "${local.oidc_host}:sub" = local.oidc_subjects
      }
    }
  }

  # Optional second path for hosts without OIDC: a base identity that may only
  # call sts:AssumeRole, guarded by an ExternalId.
  external_id_statement = {
    Sid       = "CloudOpsAIAssumeWithExternalId"
    Effect    = "Allow"
    Action    = "sts:AssumeRole"
    Principal = { AWS = var.assume_role_principal_arns }
    Condition = { StringEquals = { "sts:ExternalId" = var.external_id } }
  }

  trust_policy = {
    Version   = "2012-10-17"
    Statement = concat([local.oidc_statement], length(var.assume_role_principal_arns) > 0 ? [local.external_id_statement] : [])
  }

  readonly_policy = jsondecode(file(var.policy_file == null ? "${path.module}/../../../docs/iam/cloudops-readonly-policy.json" : var.policy_file))

  policy_actions = flatten([
    for statement in local.readonly_policy.Statement :
    statement.Action if statement.Effect == "Allow"
  ])

  # The app is recommendation-only, so every action must be a read: Describe,
  # Get or List, with no wildcards and no object contents. Plan fails otherwise.
  read_only_action  = "^[a-z0-9-]+:(Describe|Get|List)[A-Za-z]+$"
  forbidden_actions = ["s3:GetObject", "s3:GetObjectVersion", "secretsmanager:GetSecretValue", "ssm:GetParameter", "ssm:GetParameters", "kms:Decrypt"]
  non_read_actions = [
    for action in local.policy_actions : action
    if !can(regex(local.read_only_action, action)) || contains(local.forbidden_actions, action)
  ]
}

resource "aws_iam_openid_connect_provider" "vercel" {
  count = var.create_oidc_provider ? 1 : 0

  url            = "https://${local.oidc_host}"
  client_id_list = [local.oidc_audience]
  # AWS validates Vercel's certificate against its own trusted CAs, so no
  # thumbprint is needed (provider v5.81+).
}

resource "aws_iam_role" "readonly" {
  name                 = var.role_name
  description          = "CloudOps AI: read-only governance scans. Recommendation-only, no write actions."
  assume_role_policy   = jsonencode(local.trust_policy)
  max_session_duration = var.max_session_duration
}

resource "aws_iam_policy" "readonly" {
  name        = "${var.role_name}-policy"
  description = "Read-only actions CloudOps AI calls. Generated from docs/iam/cloudops-readonly-policy.json."
  policy      = jsonencode(local.readonly_policy)

  lifecycle {
    precondition {
      condition     = length(local.non_read_actions) == 0
      error_message = "The CloudOps AI policy must stay read-only. Remove: ${join(", ", local.non_read_actions)}"
    }
  }
}

resource "aws_iam_role_policy_attachment" "readonly" {
  role       = aws_iam_role.readonly.name
  policy_arn = aws_iam_policy.readonly.arn
}
