# Interface VPC endpoint for Bedrock Runtime: BedrockProvider's calls stay on
# AWS's private network instead of traversing the public internet via a NAT
# gateway — the same "least exposure" instinct as the app's own SSRF/allowlist
# defenses (docs/threat-model.md T4), applied at the network layer.

resource "aws_security_group" "bedrock_endpoint" {
  name        = "aegis-bedrock-endpoint-${var.environment}"
  description = "Allows the Aegis API to reach the Bedrock Runtime VPC endpoint on 443"
  vpc_id      = var.vpc_id
  tags        = var.tags

  egress {
    description = "HTTPS to the Bedrock Runtime endpoint"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_endpoint" "bedrock_runtime" {
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [aws_security_group.bedrock_endpoint.id]
  private_dns_enabled = true
  tags                = var.tags
}
