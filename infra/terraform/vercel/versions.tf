terraform {
  required_version = ">= 1.11"

  required_providers {
    vercel = {
      source  = "vercel/vercel"
      version = "~> 3.17"
    }
  }
}

# Reads VERCEL_API_TOKEN from the environment. Never put the token in a .tf or
# .tfvars file.
provider "vercel" {
  team = var.team
}
