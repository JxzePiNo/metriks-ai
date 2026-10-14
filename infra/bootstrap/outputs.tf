output "state_bucket_name" {
  description = "Name of the Terraform state bucket."
  value       = aws_s3_bucket.state.id
}

output "state_bucket_arn" {
  description = "ARN of the Terraform state bucket (use it in IAM policies for state access)."
  value       = aws_s3_bucket.state.arn
}

output "state_bucket_region" {
  description = "Region of the Terraform state bucket."
  value       = aws_s3_bucket.state.region
}

# Printed for the follow-up PR that switches ../terraform to this backend.
# Adjust `key` per root module/environment.
output "backend_config_hcl" {
  description = "Partial backend configuration for ../terraform (save as backend.hcl, which is not committed)."
  value       = <<-EOT
    bucket       = "${aws_s3_bucket.state.id}"
    key          = "${var.project}/terraform.tfstate"
    region       = "${var.aws_region}"
    encrypt      = true
    use_lockfile = true
  EOT
}
