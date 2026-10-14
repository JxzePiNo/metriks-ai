provider "aws" {
  region = var.aws_region

  # Safeguard: Terraform refuses to run against any other AWS account.
  # Required input (no committed default): see terraform.tfvars.example.
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = local.common_tags
  }
}
