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
| `aws_s3_bucket_policy.state` | Denies any request that is not HTTPS, and any request using TLS older than 1.2 (AWS service principals are excluded from the denies, as AWS documents, because AWS redacts the transport condition keys on service-to-service calls). |

**Region handling.** The bucket is created in `var.aws_region` (`eu-south-1`). For any region other than `us-east-1` the AWS provider (v6.69.0, checked in its source) sends the region as the `LocationConstraint` of `CreateBucket`, and `eu-south-1` is a valid value in the AWS API reference. `eu-south-1` is an opt-in region, so it must be enabled in the account (it was, in the earlier read-only audit).

**Ordering.** The configuration resources are chained with `depends_on` (ownership, public-access block, versioning, encryption, lifecycle, then the policy) so S3 gets one change at a time. In the provider source only some of these resources retry `OperationAborted`, which is why the chain is explicit. The lifecycle rule needs versioning enabled first, per the provider documentation.

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

These policies were derived from the AWS provider v6.69.0 source (the API calls each resource makes) and the AWS API documentation. They have **not** been exercised against AWS, so they are drafts, not a guaranteed minimum. If a run reports `AccessDenied`, the message names the missing action; add it deliberately and keep the resource scope.

S3 bucket-level actions take the bucket ARN (`arn:aws:s3:::<bucket>`); object-level actions take object ARNs (`arn:aws:s3:::<bucket>/<key>`).

### To run the bootstrap (one-off, temporary role)

Every action below is a bucket-level action, so the resource is the bucket ARN pattern. `metriks-ai-tfstate-*` matches `<project>-tfstate-<suffix>`; change it if you change `project`.

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
        "s3:TagResource",
        "s3:ListTagsForResource",
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
      "Resource": "arn:aws:s3:::metriks-ai-tfstate-*",
      "Condition": {
        "StringEquals": { "aws:RequestedRegion": "eu-south-1" }
      }
    }
  ]
}
```

Why these actions:

- `s3:CreateBucket`, `s3:ListBucket` (the provider's `HeadBucket` check) and the `Put*`/`Get*` actions cover the seven resources: bucket, ownership controls, public-access block, versioning, encryption, lifecycle and policy.
- The provider's bucket read also calls the ACL, CORS, website, logging, Object Lock, accelerate, request-payment and replication getters, so the matching `Get*` actions are listed even though the configuration does not set those features.
- `CreateBucket` sends the `private` canned ACL. The AWS API reference says only `s3:CreateBucket` is required in that case (`s3:PutBucketAcl` is needed for other ACLs), so `PutBucketAcl` is not granted.
- `s3:TagResource` is needed to create a bucket **with tags** (AWS API reference). In the provider source, tag reads try `s3:ListTagsForResource` first and tag writes try `s3:TagResource`/`s3:UntagResource` first; each falls back to `GetBucketTagging`/`PutBucketTagging`/`DeleteBucketTagging` when the preferred action is denied. Removing a tag later would need `s3:UntagResource` or `s3:DeleteBucketTagging`, which are not granted because the configuration never removes tags.
- **No account-level (`Resource: "*"`) actions are included.** None of the S3 calls made by these seven resources in provider v6.69.0 are account-level (for example the provider code does not call `ListAllMyBuckets` or `GetBucketLocation`), and the account safeguard uses STS `GetCallerIdentity`, which needs no IAM permission. If a future provider version or your tooling needs one, add it with its own appropriately scoped statement.
- `aws:RequestedRegion` restricts the role to `eu-south-1`.
- `s3:DeleteBucket` and `s3:DeleteBucketPolicy` are intentionally absent: this role cannot destroy the bucket.

With this policy the role can create the bucket named by the pattern. It can also be used to run `plan`, since refreshing reads use the same getters. Do not grant `s3:*`.

### To use the state afterwards (every Terraform run of `../terraform`)

Replace `<bucket>` with the bucket name and `<project>` with the project (default `metriks-ai`). Keys follow `<project>/<name>/terraform.tfstate`; the backend writes `<key>.tflock` next to the state object when `use_lockfile = true` (HashiCorp S3 backend documentation). The first statement is bucket-level (bucket ARN); the others are object-level (object ARNs).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListStateBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::<bucket>",
      "Condition": { "StringLike": { "s3:prefix": ["<project>/*"] } }
    },
    {
      "Sid": "ReadWriteState",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::<bucket>/<project>/*"
    },
    {
      "Sid": "DeleteLockFiles",
      "Effect": "Allow",
      "Action": "s3:DeleteObject",
      "Resource": "arn:aws:s3:::<bucket>/<project>/*.tflock"
    }
  ]
}
```

State access is sensitive: state can contain secret values. Grant it only to the roles that deploy, never broadly. If workspaces are used, the backend lists and writes under its `workspace_key_prefix` (default `env:`); add that prefix to the policy then.

### To inspect or restore old state versions (recovery)

Listing and reading old versions needs `s3:ListBucketVersions` on the bucket ARN and `s3:GetObjectVersion` on the object ARN, in addition to the statements above. Grant these to a recovery role, not to routine deployments.

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

- **Bad apply or corrupted state** (needs the recovery permissions above): list versions with `aws s3api list-object-versions --bucket <bucket> --prefix <key>`, then restore a previous version (copy it back as the current object with `aws s3api copy-object`, or download it and `terraform state push` after review). Retention is at least `noncurrent_version_retention_days` days *and* the newest `noncurrent_versions_to_keep` versions.
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
6. The generated `key` is `<project>/terraform.tfstate`. When a second root module or environment needs its own state, give it a distinct key under the same prefix (for example `metriks-ai/dev/terraform.tfstate`); the "use the state" policy above already covers `<project>/*`.

Until then, `init -backend=false` keeps working for `../terraform` without any AWS access.
