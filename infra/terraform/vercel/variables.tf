variable "team" {
  description = "Vercel team slug or id that owns both projects."
  type        = string
}

variable "web_project_name" {
  description = "Vercel project serving the React console."
  type        = string
  default     = "cloudops-ai"
}

variable "api_project_name" {
  description = "Vercel project running the FastAPI backend."
  type        = string
  default     = "cloudops-ai-api"
}

variable "github_repo" {
  description = "GitHub repository to deploy from, as owner/name. Null leaves the Git connection unmanaged."
  type        = string
  default     = null
}

variable "production_branch" {
  description = "Branch Vercel deploys to production."
  type        = string
  default     = "main"
}

variable "aws_role_arn" {
  description = "The read-only role from the aws root (output role_arn). Null skips the variable."
  type        = string
  default     = null

  validation {
    condition     = var.aws_role_arn == null || can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:role/", var.aws_role_arn))
    error_message = "aws_role_arn must be an IAM role ARN."
  }
}

variable "aws_region" {
  description = "Default region the backend scans."
  type        = string
  default     = "us-east-1"
}

variable "web_origins" {
  description = "Browser origins allowed by the API's CORS policy (CLOUDOPS_AI_CORS_ORIGINS)."
  type        = list(string)
  default     = ["https://cloudops-ai-roan.vercel.app"]

  validation {
    condition     = alltrue([for o in var.web_origins : can(regex("^https://[^/*]+$", o))])
    error_message = "Each origin must be an https:// origin with no path and no wildcard."
  }
}

variable "operator_emails" {
  description = "Accounts that become operators on registration (CLOUDOPS_OPERATOR_EMAILS). Marked sensitive so emails stay out of plan output."
  type        = list(string)
  default     = []
  sensitive   = true
}

variable "demo_enabled" {
  description = "Serve the public sample-data demo (CLOUDOPS_DEMO_ENABLED)."
  type        = bool
  default     = true
}
