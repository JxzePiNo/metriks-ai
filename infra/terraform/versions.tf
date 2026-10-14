terraform {
  # Intentional floor: S3 native state locking (`use_lockfile`) became generally
  # available in Terraform 1.11.0 (official changelog), and the remote backend
  # planned for the state bootstrap step relies on it. The AWS provider itself
  # does not require this: it speaks plugin protocol 5 (Terraform >= 0.12).
  # Validated with Terraform 1.16.6.
  required_version = ">= 1.11.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0" # latest 6.x at the time of writing: 6.69.0
    }
  }

  # No `backend` block on purpose: state stays local (and git-ignored) until the
  # separately approved bootstrap step creates the remote state bucket.
}
