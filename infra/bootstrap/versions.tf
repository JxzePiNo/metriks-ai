terraform {
  # Same constraints as ../terraform (see its README for the rationale).
  required_version = ">= 1.11.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # No `backend` block, deliberately: this configuration creates the remote
  # state bucket, so its own state must stay local (git-ignored). See README.md.
}
