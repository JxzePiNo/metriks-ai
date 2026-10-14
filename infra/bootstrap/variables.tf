variable "aws_region" {
  description = "AWS region for the state bucket."
  type        = string
  default     = "eu-south-1"
}

variable "project" {
  description = "Project name, used in the bucket name and tags."
  type        = string
  default     = "metriks-ai"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.project))
    error_message = "project must be 2-31 characters: lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "environment" {
  description = "Tag value for the Environment tag. The state bucket is shared by all environments, hence the default."
  type        = string
  default     = "shared"

  validation {
    condition     = contains(["shared", "dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: shared, dev, staging, prod."
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

variable "bucket_name_suffix" {
  description = "Explicit suffix that makes the bucket name globally unique: the bucket is named <project>-tfstate-<suffix>. Required, with no default, and never generated, so the name is a deliberate human choice (for example 8 random hex characters)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]{6,16}$", var.bucket_name_suffix))
    error_message = "bucket_name_suffix must be 6-16 lowercase letters or digits."
  }
}

variable "noncurrent_version_retention_days" {
  description = "Days to keep a superseded (noncurrent) state version before it becomes eligible for deletion."
  type        = number
  default     = 90

  validation {
    condition     = var.noncurrent_version_retention_days >= 30
    error_message = "noncurrent_version_retention_days must be at least 30 so state history stays recoverable."
  }
}

variable "noncurrent_versions_to_keep" {
  description = "Number of most recent noncurrent state versions that are always kept, regardless of age."
  type        = number
  default     = 10

  validation {
    condition     = var.noncurrent_versions_to_keep >= 1
    error_message = "noncurrent_versions_to_keep must be at least 1."
  }
}

variable "extra_tags" {
  description = "Additional tags merged into the common tags applied to every resource."
  type        = map(string)
  default     = {}
}
