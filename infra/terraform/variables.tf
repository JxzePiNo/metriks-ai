variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "eu-south-1"
}

variable "project" {
  description = "Project name, used in resource names and tags."
  type        = string
  default     = "metriks-ai"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.project))
    error_message = "project must be 2-31 characters: lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "allowed_account_ids" {
  description = "AWS account IDs Terraform may operate on. Required, with no default, so a run against the wrong account fails closed. Set it in a local, git-ignored terraform.tfvars."
  type        = list(string)

  validation {
    condition     = length(var.allowed_account_ids) > 0 && alltrue([for id in var.allowed_account_ids : can(regex("^[0-9]{12}$", id))])
    error_message = "allowed_account_ids must contain at least one 12-digit AWS account ID."
  }
}

variable "extra_tags" {
  description = "Additional tags merged into the common tags applied to every resource."
  type        = map(string)
  default     = {}
}
