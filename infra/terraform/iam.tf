# IAM role the Aegis API task assumes (ECS task role / EKS IRSA — the exact
# assumption mechanism depends on how a real deployment runs the container;
# the trust policy below is written for ECS Fargate as the concrete example,
# see README.md for the EKS/IRSA equivalent).
#
# See docs/adr/0001-provider-abstraction-layer.md: BedrockProvider is fully
# implemented application code — this is the least-privilege IAM shape it
# would need in a real AWS account, reviewed here without ever being applied
# (docs/adr/0003-local-first-contract-testing.md).

data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "aegis_api_task_role" {
  name               = "aegis-api-task-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = var.tags
}

# Least privilege: InvokeModel/InvokeModelWithResponseStream on exactly the
# model IDs Aegis is configured to route to (var.allowed_bedrock_model_ids),
# not "bedrock:*" on "*" — a compromised task credential can use Bedrock only
# for the models the app is actually configured to call.
data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid = "InvokeConfiguredBedrockModelsOnly"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      for model_id in var.allowed_bedrock_model_ids :
      "arn:aws:bedrock:${var.aws_region}::foundation-model/${model_id}"
    ]
  }
}

resource "aws_iam_role_policy" "aegis_bedrock_invoke" {
  name   = "aegis-bedrock-invoke"
  role   = aws_iam_role.aegis_api_task_role.id
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}

data "aws_iam_policy_document" "read_database_credentials" {
  statement {
    sid       = "ReadDatabaseCredentialsSecretOnly"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database_credentials.arn]
  }
}

resource "aws_iam_role_policy" "aegis_read_database_credentials" {
  name   = "aegis-read-database-credentials"
  role   = aws_iam_role.aegis_api_task_role.id
  policy = data.aws_iam_policy_document.read_database_credentials.json
}
