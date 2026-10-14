# Remote Terraform state bucket (S3). Creates nothing until a deliberate,
# separately approved `terraform apply` -- see README.md.
#
# Bucket configuration resources are chained with depends_on so S3 receives
# one configuration change at a time. Concurrent changes can fail with
# OperationAborted, and the AWS provider (v6.69.0 source) retries that error only
# for some of these resources. The order is:
#   ownership -> public access block -> versioning -> encryption -> lifecycle -> policy

resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name

  # Never delete a bucket that still holds state, even on destroy.
  force_destroy = false

  # Guards against an accidental `terraform destroy` or a replacing change.
  # Removing the bucket on purpose requires editing this line (see README.md).
  lifecycle {
    prevent_destroy = true
  }
}

# ACLs are disabled; the bucket owner owns every object.
resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  depends_on = [aws_s3_bucket_ownership_controls.state]

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning keeps every state revision, which is what makes a bad apply or an
# accidental overwrite recoverable.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  depends_on = [aws_s3_bucket_public_access_block.state]

  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 (AES-256, AWS-managed keys): no key to manage and no additional charge.
# A customer-managed KMS key is intentionally not used; see README.md.
resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }

  depends_on = [aws_s3_bucket_versioning.state]
}

# Bound the cost of version history without losing recoverability: superseded
# versions are deleted only when they are both older than the retention period
# and beyond the newest N noncurrent versions.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-noncurrent-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days           = var.noncurrent_version_retention_days
      newer_noncurrent_versions = var.noncurrent_versions_to_keep
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Versioning must be enabled first (provider documentation); encryption is
  # ordered before it only to keep bucket configuration changes sequential.
  depends_on = [
    aws_s3_bucket_versioning.state,
    aws_s3_bucket_server_side_encryption_configuration.state,
  ]
}

data "aws_iam_policy_document" "state_bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }

    # AWS redacts the transport keys on service-to-service calls; without this,
    # the deny could block AWS service principals (see AWS S3 policy-key docs).
    condition {
      test     = "Bool"
      variable = "aws:PrincipalIsAWSService"
      values   = ["false"]
    }
  }

  statement {
    sid     = "DenyTlsBelow12"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "NumericLessThan"
      variable = "s3:TlsVersion"
      values   = ["1.2"]
    }

    condition {
      test     = "Bool"
      variable = "aws:PrincipalIsAWSService"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state_bucket.json

  # Applied last, after the public-access block and all other bucket settings.
  depends_on = [
    aws_s3_bucket_public_access_block.state,
    aws_s3_bucket_lifecycle_configuration.state,
  ]
}
