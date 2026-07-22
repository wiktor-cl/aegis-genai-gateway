# Secrets Manager for the JWT signing key (see src/aegis/config.py's
# `jwt_signing_key` — env-var-only today, with an explicit "not a real
# secret" dev default; a real deployment injects this from here, never bakes
# a value into the image or docker-compose.yml).
#
# Deliberately no `aws_secretsmanager_secret_version` resource: creating one
# would require a real secret value in the Terraform state/plan, which is
# exactly the kind of value this repository must never contain. A real
# deployment sets the version out-of-band (console, CLI, or a separate
# pipeline step with access to a real secret), after this resource exists.

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "jwt_signing_key_kms" {
  # The standard AWS-default key policy, made explicit rather than implicit
  # (checkov CKV2_AWS_64 wants a policy on the resource, not an implied one):
  # the account root has full KMS administrative access, which is what lets
  # IAM policies (e.g. aws_iam_role_policy.aegis_read_jwt_secret) grant
  # `kms:Decrypt` to specific roles instead of managing access here too.
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

resource "aws_kms_key" "jwt_signing_key" {
  description         = "CMK for the Aegis JWT signing key secret (checkov CKV_AWS_149)"
  enable_key_rotation = true
  policy              = data.aws_iam_policy_document.jwt_signing_key_kms.json
  tags                = var.tags
}

resource "aws_kms_alias" "jwt_signing_key" {
  name          = "alias/aegis-${var.environment}-jwt-signing-key"
  target_key_id = aws_kms_key.jwt_signing_key.key_id
}

# checkov: CKV2_AWS_57 (automatic rotation) is deliberately skipped in CI's
# invocation, not fixed here — automatic rotation needs a rotation Lambda
# that understands *this specific* secret's shape (an HS256 signing key
# consumed by aegis.security.JwtService); a generic bolt-on rotation
# function would either no-op or actively break auth. Rotation here is a
# deliberate, documented manual/out-of-band operation (see docs/runbook.md),
# the same trade-off already made explicitly for API keys
# (aegis.tenancy.api_keys — rotation exists, but is caller-triggered, not on
# a timer). See infra/terraform/README.md for the full list of accepted
# findings and why.
resource "aws_secretsmanager_secret" "jwt_signing_key" {
  name        = "aegis/${var.environment}/jwt-signing-key"
  description = "HS256 signing key for Aegis JWT admin auth (aegis.tenancy.rbac). Value set out-of-band, never via Terraform."
  kms_key_id  = aws_kms_key.jwt_signing_key.arn
  tags        = var.tags
}
