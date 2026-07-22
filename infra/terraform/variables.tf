variable "aws_region" {
  description = "AWS region for Bedrock and the VPC interface endpoint."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment tag (dev/staging/prod)."
  type        = string
  default     = "dev"
}

variable "vpc_id" {
  description = "Existing VPC the Aegis API runs in. This module does not create a VPC — see README.md."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs the Bedrock interface VPC endpoint attaches to."
  type        = list(string)
}

variable "allowed_bedrock_model_ids" {
  description = <<-EOT
    Bedrock model IDs the Aegis API task role may invoke — kept in sync by
    hand with policies/routing.yaml's `providers.bedrock.model`. Least
    privilege: the IAM policy grants InvokeModel on exactly these ARNs, not
    "bedrock:*" on "*".
  EOT
  type        = list(string)
  default     = ["anthropic.claude-3-5-sonnet-20241022-v2:0"]
}

variable "tags" {
  description = "Common resource tags."
  type        = map(string)
  default = {
    Project   = "aegis"
    ManagedBy = "terraform"
  }
}
