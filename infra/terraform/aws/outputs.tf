output "role_arn" {
  description = "Set this as CLOUDOPS_AWS_ROLE_ARN on the Vercel API project (the vercel root does it for you)."
  value       = aws_iam_role.readonly.arn
}

output "oidc_provider_arn" {
  description = "The Vercel OIDC identity provider the role trusts."
  value       = local.oidc_provider_arn
}

output "allowed_subjects" {
  description = "Vercel OIDC subjects that may assume the role."
  value       = local.oidc_subjects
}

output "policy_actions" {
  description = "Every action the role can call. All are read-only."
  value       = sort(local.policy_actions)
}
