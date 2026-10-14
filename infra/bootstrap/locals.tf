locals {
  bucket_name = "${var.project}-tfstate-${var.bucket_name_suffix}"

  common_tags = merge(
    var.extra_tags,
    {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Repository  = "JxzePiNo/metriks-ai"
      Component   = "terraform-state-bootstrap"
    },
  )
}
