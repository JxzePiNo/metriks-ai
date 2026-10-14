# Terraform — Metriks AI

Infrastructure as code for Metriks AI on AWS.

**Current state: foundation only.** This directory declares the Terraform and AWS provider constraints, the provider configuration, variables, naming and tags. It defines **no resources**: running it creates, changes and destroys nothing in AWS.

## Decisions

| Topic | Decision |
| --- | --- |
| Region | `eu-south-1` (Milan) |
| Compute | ECS Fargate |
| Database | RDS PostgreSQL (pgvector evaluated in a later PR) |
| Documents | Private S3 bucket retaining original documents |
| Authentication | Dedicated Cognito User Pool for Metriks AI |
| Secrets / observability | Secrets Manager / CloudWatch |
| State | Remote S3 backend, created in a separate, explicitly approved bootstrap step |

Existing resources in the AWS account belong to other projects unless ownership is explicitly proven. In particular, do not reuse or delete the OfficeBrain Cognito pool, the CDK bootstrap resources, old MySQL leftovers or the default VPC without separate explicit approval. Metriks AI gets its own dedicated resources.

## Files

| File | Purpose |
| --- | --- |
| `versions.tf` | Terraform (`>= 1.11, < 2.0`) and AWS provider (`~> 6.0`) constraints. No backend block yet. |
| `providers.tf` | AWS provider: region, account safeguard, default tags |
| `variables.tf` | `aws_region`, `project`, `environment`, `allowed_account_ids`, `extra_tags` |
| `locals.tf` | `name_prefix` (`<project>-<environment>`) and common tags |
| `terraform.tfvars.example` | Placeholder inputs. Copy to `terraform.tfvars` (git-ignored) |
| `.terraform.lock.hcl` | Provider lock file, committed once `terraform init` has produced it |

Versions were checked against official sources at the time of writing: Terraform 1.16.6 (`releases.hashicorp.com`) and AWS provider 6.69.0 (Terraform Registry).

The `>= 1.11.0` floor is intentional. The official Terraform changelog lists "S3 native state locking is now generally available" under 1.11.0, and the remote backend planned for the bootstrap step uses it (`use_lockfile`). The AWS provider does not impose a higher minimum: its registry manifest declares plugin protocol 5, which HashiCorp documents as requiring Terraform 0.12 or later. The upper bound `< 2.0.0` guards against a future major release.

The foundation was validated (`fmt`, `init -backend=false`, `validate`) with Terraform 1.16.6 in the official `hashicorp/terraform` Docker image, pinned by digest `sha256:bfffc1ded5fbf0a17beaaf22eb4793980abdb19d0761ff6a3a0efb2ab4d9b316`.

### Provider lock file

`.terraform.lock.hcl` pins the AWS provider (6.69.0) and is committed. It currently contains checksums for `linux_amd64` only, because that is where it was generated. On another platform (for example Windows or macOS), run once and commit the result:

```bash
terraform providers lock -platform=windows_amd64 -platform=linux_amd64 \
  -platform=linux_arm64 -platform=darwin_amd64 -platform=darwin_arm64
```

## Account safeguard

`allowed_account_ids` has **no default** and must be set to the 12-digit ID of the intended AWS account (an account ID is not a secret, but it is kept out of committed defaults). The AWS provider refuses to run against any other account, so a run with the wrong credentials fails instead of touching the wrong environment.

```hcl
# terraform.tfvars  (git-ignored)
allowed_account_ids = ["<12-digit account id>"]
```

## Validation (no AWS access needed)

These commands never contact AWS and never create resources:

```bash
cd infra/terraform
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

`init` downloads the provider from the Terraform Registry (internet access required). `validate` does not need `allowed_account_ids` or credentials. **Never run `terraform apply` or `destroy` from this PR.** A successful `plan` would not prove that deployment permissions are adequate, and is not used for validation here.

Local `terraform.tfstate`, `.terraform/`, `*.tfvars` and plan files are git-ignored. Never commit them.

## Identity and permissions (design for future steps)

Use **temporary credentials from IAM Identity Center** (SSO), not long-lived IAM user access keys:

```bash
aws sso login --profile <profile>
export AWS_PROFILE=<profile>
```

Nothing in this repository stores credentials. Create separate permission sets, each as narrow as practical:

1. **This PR:** no AWS access.
2. **State bootstrap:** create and configure one S3 bucket (versioning, default encryption, public access block, TLS-only policy), optionally a KMS key. Day to day, state access needs only `s3:ListBucket` on the bucket and `s3:GetObject`/`s3:PutObject`/`s3:DeleteObject` on the state and `*.tflock` objects.
3. **Infrastructure PRs:** create the services below (EC2/VPC, ECS, ECR, ELB, RDS, S3, Cognito, Secrets Manager, CloudWatch Logs, KMS, IAM). Scope actions and resources to `metriks-ai-*` names and the `eu-south-1` region where the service allows it.

**Treat `iam:PassRole` as sensitive.** It lets a principal hand a role to an AWS service (for example an ECS task execution role), so an unrestricted `PassRole` combined with `iam:CreateRole` or `iam:AttachRolePolicy` is a privilege-escalation path. Restrict it to specific role ARNs (`metriks-ai-*`), add `iam:PassedToService` conditions (for example `ecs-tasks.amazonaws.com`), and apply a **permissions boundary** to every role Terraform creates. Prefer a distinct, reviewed permission set for IAM changes.

Not verified for this account: which permission sets exist and what they allow, service quotas (for example Fargate vCPU limits) and available credits. Check in the console: IAM Identity Center → permission sets, Service Quotas, and Billing → Credits.

## State bootstrap design (separate, approved step)

The bucket is defined (but **not created**) in [`../bootstrap`](../bootstrap/README.md), a separate Terraform root with local state. State here stays local until the bucket has been created with explicit approval and a follow-up PR switches this root to it. Planned design:

1. A dedicated S3 bucket (for example `metriks-ai-tfstate-<account>-eu-south-1`) with versioning, SSE (KMS or S3-managed), all public access blocked, TLS-only policy and lifecycle rules for old versions. Created once, either by a tiny separate Terraform root with local state or manually, then protected from deletion.
2. A `backend "s3"` block with `use_lockfile = true` (S3 native locking; DynamoDB locking is deprecated per the HashiCorp docs), `encrypt = true`, region `eu-south-1`.
3. `terraform init -migrate-state` to move local state to the bucket, after which the local file is removed.

No backend block exists in this PR because pointing at a bucket that does not exist would break `init`.

## Networking design (future PR) and trade-offs

Planned: a **dedicated VPC** across at least two AZs, with public subnets (ALB), application subnets (Fargate) and isolated database subnets (no route to the internet). Security groups: ALB accepts 80/443 from the internet; tasks accept traffic only from the ALB security group; RDS accepts 5432 only from the task security group and is not publicly accessible.

The open question is how tasks reach the outside: ECR image pulls, CloudWatch Logs, Secrets Manager, and external APIs such as OpenAI. Prices below are eu-south-1 on-demand list prices from AWS's public price files at the time of writing (730 h/month).

| Option | Security | Cost | Notes |
| --- | --- | --- | --- |
| **A. Tasks in public subnets, public IP, no NAT** | Inbound is locked down by security groups, but tasks have public addresses and outbound traffic is unrestricted | Public IPv4 $0.005/h each, about $3.65/month per task | Cheapest and simplest. Weakest posture. |
| **B. Private subnets + NAT Gateway** | Tasks have no public IP; outbound is centralised on NAT addresses | NAT $0.05/h (about $36.50/month) per NAT **plus $0.05/GB** processed; one per AZ for AZ-level resilience | The usual production baseline. Required if tasks must call external APIs while staying private. A single NAT is a cost-saving, AZ-level single point of failure. |
| **C. Private subnets + VPC endpoints, no NAT** | Traffic to AWS services stays on the AWS network | Interface endpoint $0.01155/h (about $8.43/month) per endpoint per AZ, plus $0.01/GB; the S3 gateway endpoint is free | Needs endpoints for ECR (api, dkr), Logs and Secrets Manager. **Cannot reach OpenAI**, so it must be combined with NAT or a proxy. |
| **D. B + C (production target)** | Strongest | NAT plus endpoints | Endpoints cut NAT data charges for ECR, Logs and S3 traffic and keep it private. |

Recommendation: do not rule NAT out. Start with option **B** (private subnets, a NAT Gateway) plus the free S3 gateway endpoint, since the backend must call OpenAI from private subnets. Add interface endpoints when NAT data-processing costs justify them. Use one NAT in `dev` and one per AZ in `prod`. Option A is acceptable only for a short-lived dev environment. The final choice is a decision for the networking PR.

Other cost drivers (eu-south-1): Fargate $0.0486 per vCPU-hour and $0.0053 per GB-hour; ALB $0.0265/h plus $0.0084 per LCU-hour; RDS PostgreSQL `db.t4g.micro` $0.018/h single-AZ and $0.036/h Multi-AZ (Multi-AZ for production availability), gp storage $0.133/GB-month; S3 Standard $0.024/GB-month; Secrets Manager $0.40 per secret per month; CloudWatch Logs ingestion $0.60/GB and storage $0.032/GB-month. These are list prices, not an estimate: no monthly total is given because usage assumptions are not fixed yet.

## Roadmap

| Step | Content |
| --- | --- |
| Terraform foundation | This directory |
| State bootstrap | Remote state bucket and backend, with explicit approval |
| Networking and registry | VPC, subnets, routing, NAT/endpoints decision, ECR |
| Database and storage | RDS PostgreSQL (and the pgvector evaluation), private S3 documents bucket, KMS |
| Backend / frontend deployment | ECS cluster, task definitions, services, ALB, logs |
| Authentication | Dedicated Cognito User Pool and app clients |
| Secrets and observability | Secrets Manager, CloudWatch alarms and dashboards |
| CI/CD | Pipeline with OIDC-based short-lived credentials |
