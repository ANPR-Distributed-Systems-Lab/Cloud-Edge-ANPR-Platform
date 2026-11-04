# IAM role that the "start environment" and "stop environment" workflows assume (via
# OpenID Connect) to switch the environment on and off: ECS task counts and RDS instances.
#
# Separate from the deploy role on purpose: it cannot push images or register task
# definitions, and the deploy role cannot start or stop anything.
#
# Scope is by naming convention, so new services and databases are covered without
# touching this role: every ECS service in the cluster and every RDS instance whose
# identifier starts with the environment prefix (e.g. anpr-dev-).

variable "name" {
  description = "Role name, e.g. anpr-dev-env-power."
  type        = string
}

variable "oidc_provider_arn" {
  type = string
}

variable "github_repository" {
  description = "Only workflows of this repository may assume the role, as owner/name."
  type        = string
}

variable "github_owner_id" {
  description = "Numeric GitHub id of the owner (it appears in the token's sub claim)."
  type        = string
}

variable "github_repository_id" {
  description = "Numeric GitHub id of the repository."
  type        = string
}

variable "github_environment" {
  description = "Only jobs running in this GitHub environment may assume the role."
  type        = string
}

variable "ecs_cluster_name" {
  description = "Cluster whose services may be started and stopped."
  type        = string
}

variable "rds_name_prefix" {
  description = "RDS instances whose identifier starts with this prefix may be started and stopped, e.g. anpr-dev."
  type        = string
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region

  github_owner = split("/", var.github_repository)[0]
  github_name  = split("/", var.github_repository)[1]

  # Same subject format as the deploy role: immutable numeric ids included.
  oidc_subject = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_name}@${var.github_repository_id}:environment:${var.github_environment}"
}

# ---------------------------------------------------------------- trust policy

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [local.oidc_subject]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.name
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

# ---------------------------------------------------------------- permissions

data "aws_iam_policy_document" "permissions" {
  # Find the services of the cluster. IAM evaluates ListServices against the services of
  # the cluster (service/<cluster>/*), not the cluster ARN; both are listed to be safe.
  statement {
    sid     = "EcsListServices"
    actions = ["ecs:ListServices"]
    resources = [
      "arn:aws:ecs:${local.region}:${local.account_id}:cluster/${var.ecs_cluster_name}",
      "arn:aws:ecs:${local.region}:${local.account_id}:service/${var.ecs_cluster_name}/*",
    ]
  }

  # Read the finops:start-count tag, change the task count and wait for the rollout.
  statement {
    sid = "EcsSwitchServices"
    actions = [
      "ecs:DescribeServices",
      "ecs:ListTagsForResource",
      "ecs:UpdateService",
    ]
    resources = ["arn:aws:ecs:${local.region}:${local.account_id}:service/${var.ecs_cluster_name}/*"]
  }

  # Describing instances is read-only; listing them cannot be limited to a resource.
  statement {
    sid       = "RdsDescribe"
    actions   = ["rds:DescribeDBInstances"]
    resources = ["*"]
  }

  statement {
    sid       = "RdsStartStop"
    actions   = ["rds:StartDBInstance", "rds:StopDBInstance"]
    resources = ["arn:aws:rds:${local.region}:${local.account_id}:db:${var.rds_name_prefix}-*"]
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "environment-power"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.permissions.json
}

output "role_arn" {
  description = "Value for the AWS_POWER_ROLE_ARN variable in the GitHub environment."
  value       = aws_iam_role.this.arn
}
