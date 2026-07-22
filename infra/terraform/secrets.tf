# Secrets Manager for the Postgres credential the API connects with (see
# src/aegis/config.py's `database_url` — a full connection string with an
# embedded password, `postgresql+asyncpg://aegis:aegis@...` in dev/compose;
# a real deployment injects the password from here instead of baking it into
# an image or docker-compose.yml).
#
# Deliberately no `aws_secretsmanager_secret_version` resource: creating one
# would require a real secret value in the Terraform state/plan, which is
# exactly the kind of value this repository must never contain. A real
# deployment sets the version out-of-band (console, CLI, or a separate
# pipeline step with access to a real secret), after this resource exists.

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "database_credentials_kms" {
  # The standard AWS-default key policy, made explicit rather than implicit
  # (checkov CKV2_AWS_64 wants a policy on the resource, not an implied one):
  # the account root has full KMS administrative access, which is what lets
  # IAM policies (e.g. aws_iam_role_policy.aegis_read_database_credentials)
  # grant `kms:Decrypt` to specific roles instead of managing access here too.
  # `actions=["kms:*"]`/`resources=["*"]` here trips checkov's generic
  # IAM-wildcard rules (CKV_AWS_109/111/CKV_AWS_356), but this is a *key
  # policy*, where "*" scopes to "this key" by construction, not "every AWS
  # resource" — and this exact shape is AWS's own documented default KMS key
  # policy. Skipped explicitly in CI's checkov invocation, not silently.
  statement {
    sid       = "EnableIamUserPermissions"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_kms_key" "database_credentials" {
  description         = "CMK for the Aegis Postgres credential secret (checkov CKV_AWS_149)"
  enable_key_rotation = true
  policy              = data.aws_iam_policy_document.database_credentials_kms.json
  tags                = var.tags
}

resource "aws_kms_alias" "database_credentials" {
  name          = "alias/aegis-${var.environment}-database-credentials"
  target_key_id = aws_kms_key.database_credentials.key_id
}

# checkov: CKV2_AWS_57 (automatic rotation) is deliberately skipped in CI's
# invocation, not fixed here. AWS's built-in Secrets Manager rotation
# template for Postgres assumes RDS/Aurora (it calls the RDS API to manage
# the rotation window); this project's docker-compose.yml runs a plain
# `postgres:16-alpine` container, not RDS, so that template doesn't apply
# as-is. A real deployment on RDS would enable native rotation trivially —
# noted here rather than pretending it's already wired up for infrastructure
# this repository doesn't actually provision. Rotation here is a deliberate,
# documented manual/out-of-band operation (see docs/runbook.md), the same
# trade-off already made explicitly for API keys (aegis.tenancy.api_keys —
# rotation exists, but is caller-triggered, not on a timer). See
# infra/terraform/README.md for the full list of accepted findings and why.
resource "aws_secretsmanager_secret" "database_credentials" {
  name        = "aegis/${var.environment}/database-credentials"
  description = "Postgres credential for the Aegis API (aegis.config.settings.database_url). Value set out-of-band, never via Terraform."
  kms_key_id  = aws_kms_key.database_credentials.arn
  tags        = var.tags
}
