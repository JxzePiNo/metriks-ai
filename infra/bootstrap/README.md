# Terraform state bootstrap

Creates the S3 bucket that will hold the remote Terraform state for Metriks AI.

**Status: not applied.** This directory only *defines* the bucket. Nothing exists in AWS until someone runs `terraform apply` here, which is a separate, deliberate operation that requires explicit approval. Merging this configuration changes nothing in AWS, and `../terraform` does **not** use the S3 backend yet.

This is a separate Terraform root (`infra/bootstrap/`) with **local state**: the remote bucket cannot store the state of the configuration that creates it.

## What it creates

| Resource | Purpose |
| --- | --- |
| `aws_s3_bucket.state` | Bucket `<project>-tfstate-<suffix>` in `eu-south-1`. `force_destroy = false` and `prevent_destroy = true`. |
| `aws_s3_bucket_ownership_controls.state` | `BucketOwnerEnforced`: ACLs disabled, the bucket owner owns all objects. |
| `aws_s3_bucket_public_access_block.state` | All four public-access blocks on. |
| `aws_s3_bucket_versioning.state` | Versioning enabled: every state revision is kept. |
| `aws_s3_bucket_server_side_encryption_configuration.state` | Default encryption with SSE-S3 (AES-256). |
| `aws_s3_bucket_lifecycle_configuration.state` | Expires old noncurrent versions (default: older than 90 days **and** beyond the newest 10) and aborts incomplete multipart uploads after 7 days. |
| `aws_s3_bucket_policy.state` | Denies any request that is not HTTPS, and any request using TLS older than 1.2. |

No DynamoDB table is created: locking uses S3 native locking (`use_lockfile = true`), which is generally available since Terraform 1.11.0 and is the approach HashiCorp documents (DynamoDB-based locking is deprecated).

## Files

| File | Purpose |
| --- | --- |
| `versions.tf` | Terraform and AWS provider constraints (same as `../terraform`). No backend block. |
| `providers.tf` | AWS provider: region, account safeguard, default tags |
| `variables.tf` | Inputs and validation |
| `locals.tf` | Bucket name and common tags |
| `main.tf` | The bucket and its protections |
| `outputs.tf` | Bucket name, ARN, region and a ready-to-use partial backend configuration |
| `terraform.tfvars.example` | Placeholder inputs. Copy to `terraform.tfvars` (git-ignored). |

## Safe naming

S3 bucket names are global across all AWS accounts, so a name cannot be guessed to be free. The bucket is named `<project>-tfstate-<bucket_name_suffix>` and the suffix is a **required input with no default** that is never generated automatically:

```bash
openssl rand -hex 4        # for example: 3f9a1c7e
```

If the name is already taken, `apply` fails with `BucketAlreadyExists` and creates nothing; choose another suffix. The account ID is deliberately not part of the name. Note the final name in your own records, since it is needed for the backend configuration.

## Inputs

| Variable | Default | Notes |
| --- | --- | --- |
| `allowed_account_ids` | none (required) | Provider refuses any other account |
| `bucket_name_suffix` | none (required) | 6-16 lowercase letters/digits |
| `aws_region` | `eu-south-1` | |
| `project` | `metriks-ai` | |
| `environment` | `shared` | Tag only; the bucket serves all environments |
| `noncurrent_version_retention_days` | `90` (min 30) | |
| `noncurrent_versions_to_keep` | `10` (min 1) | |
| `extra_tags` | `{}` | |

## Prerequisites

- Terraform `>= 1.11.0, < 2.0.0`
- Temporary AWS credentials for the intended account, preferably from IAM Identity Center (`aws sso login --profile <profile>`), not long-lived IAM user keys
- An identity allowed to run the bootstrap (see below)

## Static validation (no AWS access, no credentials)

```bash
cd infra/bootstrap
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

`validate` needs neither credentials nor input values. These commands never create resources.

## Bootstrap workflow (separate, explicitly approved operation)

Do **not** run this as part of merging the PR. Run it only after explicit approval of the exact plan.

1. **Configure inputs**
   ```bash
   cd infra/bootstrap
   cp terraform.tfvars.example terraform.tfvars   # git-ignored; set real values locally
   ```
2. **Authenticate** with temporary credentials for the intended account (see above).
3. **Initialize** (local state):
   ```bash
   terraform init
   ```
4. **Create and inspect a plan** (read-only; it calls AWS but changes nothing):
   ```bash
   terraform plan -out=tfplan
   terraform show tfplan
   ```
   Expected: `7 to add, 0 to change, 0 to destroy`, all for the resources in the table above, in `eu-south-1`, with the bucket name you chose. Anything else (changes, destroys, another region or account) is a reason to stop. `tfplan` is git-ignored; do not commit it.
5. **Apply the reviewed plan, after explicit approval:**
   ```bash
   terraform apply tfplan
   ```
6. **Record the outputs** (`terraform output`) and **back up the local `terraform.tfstate`** of this bootstrap root outside the repository (it contains no secrets, but it is the only record linking Terraform to the bucket). It stays git-ignored.

## IAM permissions

These are least-privilege **drafts**, not yet exercised against AWS. When running them the first time, an `AccessDenied` message will name any missing action; adjust deliberately and keep the resource scope.

### To run the bootstrap (one-off, temporary role)

Scope to the bucket name pattern; replace `metriks-ai-tfstate-*` if you change `project`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ManageStateBucket",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:GetBucketTagging",
        "s3:PutBucketTagging",
        "s3:GetBucketVersioning",
        "s3:PutBucketVersioning",
        "s3:GetEncryptionConfiguration",
        "s3:PutEncryptionConfiguration",
        "s3:GetBucketPublicAccessBlock",
        "s3:PutBucketPublicAccessBlock",
        "s3:GetBucketOwnershipControls",
        "s3:PutBucketOwnershipControls",
        "s3:GetLifecycleConfiguration",
        "s3:PutLifecycleConfiguration",
        "s3:GetBucketPolicy",
        "s3:PutBucketPolicy",
        "s3:GetBucketAcl",
        "s3:GetBucketCORS",
        "s3:GetBucketWebsite",
        "s3:GetBucketLogging",
        "s3:GetBucketObjectLockConfiguration",
        "s3:GetAccelerateConfiguration",
        "s3:GetBucketRequestPayment",
        "s3:GetReplicationConfiguration"
      ],
      "Resource": "arn:aws:s3:::metriks-ai-tfstate-*"
    }
  ]
}
```

`s3:DeleteBucket` and `s3:DeleteBucketPolicy` are intentionally absent: the bucket is not meant to be destroyed by this role. Do not grant `s3:*`.

### To use the state afterwards (every Terraform run of `../terraform`)

Replace `<bucket>` and the key with the real values. With `use_lockfile = true` the lock is the object `<key>.tflock` next to the state object (per the HashiCorp S3 backend documentation).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListStateBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<bucket>",
      "Condition": { "StringLike": { "s3:prefix": ["metriks-ai/*"] } }
    },
    {
      "Sid": "ReadWriteState",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::<bucket>/metriks-ai/terraform.tfstate"
    },
    {
      "Sid": "ReadWriteDeleteLock",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::<bucket>/metriks-ai/terraform.tfstate.tflock"
    }
  ]
}
```

State access is sensitive: state can contain secret values. Grant it only to the roles that deploy, never broadly.

## Encryption: SSE-S3 versus a customer-managed KMS key

SSE-S3 is used because there is no requirement for customer-controlled keys yet:

| | SSE-S3 (chosen) | SSE-KMS with a customer-managed key |
| --- | --- | --- |
| Cost | No additional charge | Per-key monthly fee plus per-request fees (see AWS KMS pricing; not estimated here) |
| Operations | Nothing to manage | Key policy, rotation and deletion to manage; a mistake can make state unreadable |
| Access control | Bucket and IAM permissions only | Adds a second control point (`kms:Decrypt`), and CloudTrail records key use |
| Fit | Meets encryption-at-rest for this bucket | Needed if policy requires key-level audit or separation of duties |

State files can contain secrets, so the real protection here is tight IAM access plus TLS-only transport. If a compliance requirement later calls for KMS, switching is a small, reviewable change (`sse_algorithm = "aws:kms"` plus a key and the matching permissions), and existing objects would then need re-encrypting.

## Cost

The bucket stores a few small state files. Costs are driven by version history, not by the live state. S3 Standard in `eu-south-1` is listed at $0.024 per GB-month (AWS public price list, at the time of writing). The lifecycle rule bounds history, and state files are typically kilobytes to a few megabytes, so storage and request charges are expected to be negligible. Not verified: the account's free-tier status and real usage. There is no DynamoDB table and no KMS key to pay for.

## Recovery and protection

- **Bad apply or corrupted state:** list versions with `aws s3api list-object-versions --bucket <bucket> --prefix <key>`, then restore a previous version (copy it back as the current object with `aws s3api copy-object`, or download it and `terraform state push` after review). Retention is at least `noncurrent_version_retention_days` days *and* the newest `noncurrent_versions_to_keep` versions.
- **Accidental object deletion:** with versioning a delete only adds a delete marker; removing the marker restores the object.
- **Accidental bucket deletion:** `force_destroy = false` makes a non-empty bucket undeletable through Terraform, and `prevent_destroy = true` makes Terraform refuse any plan that would destroy or replace it. To delete it on purpose, first migrate state elsewhere, empty all versions, remove the `prevent_destroy` line in a reviewed change, and get explicit approval.
- **Lost local bootstrap state:** the bucket still exists but Terraform no longer tracks it. Recover by re-creating `terraform.tfvars` with the same values and importing the seven resources (`terraform import` mutates state and requires explicit approval), or keep a backup as advised in step 6.
- **Not enabled:** MFA Delete (cannot be configured through Terraform and needs the root user) and S3 Object Lock. Cross-region replication of state is not configured; consider it if regional loss of `eu-south-1` state is unacceptable.
- **Stale locks:** a crashed run can leave `<key>.tflock`. Confirm nobody is running Terraform, then `terraform force-unlock <id>` with the ID from the error.

## Follow-up PR: switch `../terraform` to the S3 backend

Only after the bucket actually exists (separate PR, separate approval):

1. Add a partial backend block to `infra/terraform/versions.tf`:
   ```hcl
   terraform {
     backend "s3" {}
   }
   ```
2. Save the `backend_config_hcl` output as `infra/terraform/backend.hcl` (git-ignored; it contains the bucket name and `use_lockfile = true`, `encrypt = true`, region `eu-south-1`).
3. Grant the deploying role the "use the state" permissions above.
4. Migrate the existing local state: `terraform init -backend-config=backend.hcl -migrate-state`.
5. Verify with `terraform state list`, then remove the local state file.
6. Use a distinct `key` per root module or environment (for example `metriks-ai/dev/terraform.tfstate`).

Until then, `init -backend=false` keeps working for `../terraform` without any AWS access.
