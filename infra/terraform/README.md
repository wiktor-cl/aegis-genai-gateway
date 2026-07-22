# Aegis — AWS Terraform (validated, never applied)

**This is never `terraform apply`'d in this repository.** CI runs `terraform validate` and
`tflint` only (see `.github/workflows/ci.yml`, job `iac-validate`) — there are no AWS
credentials configured anywhere in CI to apply it with. See
[ADR-0003](../../docs/adr/0003-local-first-contract-testing.md) and the root README's
zero-cost constraint.

## What this provisions (if it were applied)

- `iam.tf` — an IAM role for the Aegis API's ECS task, with a policy granting
  `bedrock:InvokeModel`/`InvokeModelWithResponseStream` on exactly the model IDs
  `policies/routing.yaml` is configured to use (`var.allowed_bedrock_model_ids`) — not
  `bedrock:*` on `*`. A compromised task credential can invoke only the models the app is
  actually configured to call.
- `secrets.tf` — a Secrets Manager secret for the Postgres credential the API connects with
  (`src/aegis/config.py`'s `database_url`). Deliberately no secret *version* resource: that
  would require a real secret value to exist in a Terraform plan/state, which this repository
  must never contain. A real deployment sets the value out-of-band, after this resource exists.
- `network.tf` — an interface VPC endpoint for Bedrock Runtime, so calls stay on AWS's private
  network instead of going out through a NAT gateway to the public internet.

## What this does NOT provision

No VPC, subnets, ECS cluster/service, RDS/ElastiCache, or load balancer — this module assumes
those already exist (`var.vpc_id`, `var.private_subnet_ids`) rather than re-implementing a full
reference network stack, which would dilute the point being demonstrated (least-privilege IAM
scoped to this app's actual Bedrock usage, and network isolation for that specific call path).

## Running the validation locally

```bash
cd infra/terraform
terraform init -backend=false   # no backend is configured — see versions.tf
terraform fmt -check
terraform validate
tflint --init && tflint
checkov -d . --framework terraform --skip-check CKV2_AWS_57,CKV_AWS_109,CKV_AWS_111,CKV_AWS_356
```

## Accepted checkov findings (skipped explicitly, not silently)

| Check | What it wants | Why skipped here |
|---|---|---|
| `CKV2_AWS_57` | Automatic Secrets Manager rotation | AWS's built-in Postgres rotation template assumes RDS/Aurora; this project's `docker-compose.yml` runs plain `postgres:16-alpine`, not RDS, so the template doesn't apply as-is. Rotation is deliberately manual/out-of-band here — see `secrets.tf` and `docs/runbook.md`. |
| `CKV_AWS_109`, `CKV_AWS_111`, `CKV_AWS_356` | No `"*"` in an IAM policy's actions/resources | These fire on `database_credentials_kms`'s key policy, which is AWS's own documented default KMS key-policy shape (`kms:*` on `*` scoped to the account root principal) — in a *key* policy, `resources=["*"]` means "this key," not "every AWS resource." |

Every other resource passes checkov, tflint (with the `aws` ruleset), and `terraform validate`
clean — see `.github/workflows/ci.yml`, job `iac-validate`.

## Why Terraform for AWS, Bicep for Azure

Each cloud's own first-party-adjacent tool, not a single tool forced across both — consistent
with [ADR-0007](../../docs/adr/0007-multi-cloud-over-vendor-lock-in.md)'s reasoning that teams
adopting Aegis are usually already standardized per-cloud on their own IaC tooling and review
processes; asking an AWS-standardized team to review Bicep (or vice versa) would add friction
this project has no reason to introduce.
