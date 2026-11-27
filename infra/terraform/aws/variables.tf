variable "region" {
  description = "Region for the provider. IAM is global, so this only affects the STS endpoint."
  type        = string
  default     = "us-east-1"
}

variable "role_name" {
  description = "Name of the read-only role the API assumes."
  type        = string
  default     = "cloudops-ai-readonly"
}

variable "vercel_team_slug" {
  description = "Vercel team slug. The OIDC issuer is https://oidc.vercel.com/<slug> (team issuer mode)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,99}$", var.vercel_team_slug))
    error_message = "Use the team slug as it appears in Vercel URLs: lowercase letters, digits and hyphens."
  }
}

variable "vercel_api_project_name" {
  description = "Name of the Vercel project that runs the FastAPI backend."
  type        = string
  default     = "cloudops-ai-api"
}

variable "vercel_environments" {
  description = "Vercel environments allowed to assume the role. Keep this to production unless previews need real AWS data."
  type        = list(string)
  default     = ["production"]

  validation {
    condition     = length(var.vercel_environments) > 0 && alltrue([for e in var.vercel_environments : contains(["production", "preview", "development"], e)])
    error_message = "Allowed values: production, preview, development."
  }
}

variable "create_oidc_provider" {
  description = "Create the Vercel OIDC identity provider. Set false and pass existing_oidc_provider_arn if the account already has one."
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing oidc.vercel.com/<slug> provider, used when create_oidc_provider is false."
  type        = string
  default     = null

  validation {
    condition     = var.create_oidc_provider || can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:oidc-provider/oidc\\.vercel\\.com/", var.existing_oidc_provider_arn))
    error_message = "Set existing_oidc_provider_arn to the oidc.vercel.com provider's ARN when create_oidc_provider is false."
  }
}

variable "assume_role_principal_arns" {
  description = "Optional IAM principals allowed to call sts:AssumeRole on the role (the ExternalId path for non-Vercel hosts). Empty disables it."
  type        = list(string)
  default     = []
}

variable "external_id" {
  description = "ExternalId required for the sts:AssumeRole path. Required when assume_role_principal_arns is set."
  type        = string
  default     = null
  sensitive   = true

  validation {
    condition     = length(var.assume_role_principal_arns) == 0 || try(length(var.external_id) >= 16, false)
    error_message = "The sts:AssumeRole path needs an external_id of at least 16 characters."
  }
}

variable "policy_file" {
  description = "Path to the permissions policy. Defaults to docs/iam/cloudops-readonly-policy.json; only tests override it."
  type        = string
  default     = null
}

variable "max_session_duration" {
  description = "Maximum session length in seconds. The backend asks for one hour."
  type        = number
  default     = 3600
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    Project   = "cloudops-ai"
    ManagedBy = "terraform"
    Access    = "read-only"
  }
}
