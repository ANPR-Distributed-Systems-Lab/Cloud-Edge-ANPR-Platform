# IAM role that a GitHub Actions workflow assumes (via OpenID Connect) to deploy one
# ECS service. No long-lived AWS keys exist anywhere: GitHub proves who is calling
# with a short-lived signed token, and AWS exchanges it for temporary credentials.
#
# The role is deliberately narrow: it can push images to ONE repository and update
# ONE service, and it can be assumed only by ONE repository and GitHub environment.

variable "name" {
  description = "Role name, e.g. anpr-dev-operations-deploy."
  type        = string
}

variable "oidc_provider_arn" {
  description = "ARN of the account's GitHub OIDC identity provider."
  type        = string
}

variable "github_repository" {
  description = "Only workflows of this repository may assume the role, as owner/name."
  type        = string
}

variable "github_environment" {
  description = "Only jobs running in this GitHub environment may assume the role (e.g. dev). Environments can add required reviewers."
  type        = string
}

variable "ecr_repository_arn" {
  type = string
}

variable "ecs_service_arn" {
  type = string
}

variable "pass_role_arns" {
  description = "Roles the service uses (task execution and task role); the deployer must be allowed to hand them to ECS."
  type        = list(string)
}

# ---------------------------------------------------------------- trust policy
# WHO may assume the role. Both conditions must hold.

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    # The token was issued for AWS STS...
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # ...and comes from this repository and environment. "sub" is the claim that
    # identifies the caller; without this condition any GitHub repository could assume the role.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.github_environment}"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.name
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

# ---------------------------------------------------------------- permissions
# WHAT the role may do once assumed (least privilege).

data "aws_iam_policy_document" "permissions" {
  # Docker login. This action cannot be scoped to a resource.
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Push (and check for an existing tag) in this one repository only.
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:DescribeImages",
    ]
    resources = [var.ecr_repository_arn]
  }

  # Task definition actions do not support resource-level permissions in IAM.
  statement {
    sid       = "EcsTaskDefinitions"
    actions   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid       = "EcsUpdateService"
    actions   = ["ecs:UpdateService", "ecs:DescribeServices"]
    resources = [var.ecs_service_arn]
  }

  # A new task definition references the execution and task roles; passing them to
  # ECS requires explicit permission, restricted to the ECS tasks service.
  statement {
    sid       = "PassServiceRoles"
    actions   = ["iam:PassRole"]
    resources = var.pass_role_arns

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "deploy"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.permissions.json
}

output "role_arn" {
  description = "Value for the AWS_DEPLOY_ROLE_ARN variable in the GitHub environment."
  value       = aws_iam_role.this.arn
}
