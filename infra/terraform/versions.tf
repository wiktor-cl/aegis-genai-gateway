terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # No backend block on purpose: this configuration is validated only
  # (`terraform validate` / `tflint` / `checkov`), never `terraform apply` —
  # see README.md and docs/adr/0003-local-first-contract-testing.md. A real
  # deployment would add an S3 + DynamoDB remote backend here; adding one
  # that's never actually used would just be unexercised code.
}

provider "aws" {
  region = var.aws_region
}
