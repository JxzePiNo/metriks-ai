locals {
  # Prefix for resource names, e.g. "metriks-ai-dev".
  name_prefix = "${var.project}-${var.environment}"

  common_tags = merge(
    var.extra_tags,
    {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
      Repository  = "JxzePiNo/metriks-ai"
    },
  )
}
