output "aegis_api_task_role_arn" {
  description = "IAM role ARN the Aegis API task assumes to call Bedrock and read its JWT secret."
  value       = aws_iam_role.aegis_api_task_role.arn
}

output "jwt_signing_key_secret_arn" {
  description = "Secrets Manager secret ARN — set its value out-of-band, never via Terraform."
  value       = aws_secretsmanager_secret.jwt_signing_key.arn
}

output "jwt_signing_key_kms_key_arn" {
  description = "CMK protecting the JWT signing key secret."
  value       = aws_kms_key.jwt_signing_key.arn
}

output "bedrock_runtime_vpc_endpoint_id" {
  description = "VPC interface endpoint ID for Bedrock Runtime."
  value       = aws_vpc_endpoint.bedrock_runtime.id
}
