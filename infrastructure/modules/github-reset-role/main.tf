# IAM role that the "Reset environment" workflow assumes (via OpenID Connect) to empty the data of the
# environment: database, DynamoDB tables, storage bucket, Cognito users and SQS queues
# (infrastructure/scripts/environment_reset.py).
#
# Destructive on purpose, so it is narrow: every statement is limited to the resources of this
# environment (the name prefix, one bucket, one user pool), it changes no infrastructure, and it can be
# assumed only by one repository and one GitHub environment, which accepts trusted branches only.

variable "name" {
  description = "Role name, e.g. anpr-dev-reset."
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

variable "name_prefix" {
  description = "Prefix of the queues and tables that may be emptied, e.g. anpr-dev."
  type        = string
}

variable "ecs_cluster_name" {
  description = "Cluster whose services are scaled to 0 while the data is deleted and restored afterwards."
  type        = string
}

variable "storage_bucket_arn" {
  type = string
}

variable "user_pool_arn" {
  type = string
}

variable "database_parameter_arns" {
  description = "SSM parameters with the address and the user name of the database (not the password)."
  type        = list(string)
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region

  github_owner = split("/", var.github_repository)[0]
  github_name  = split("/", var.github_repository)[1]

  # Same subject format as the other GitHub roles: immutable numeric ids included.
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
  # Listing cannot be limited to a resource.
  statement {
    sid = "List"
    actions = [
      "sqs:ListQueues",
      "dynamodb:ListTables",
      "cognito-idp:ListUserPools",
      "rds:DescribeDBInstances",
      "ec2:DescribeInstances",
      "ssm:DescribeInstanceInformation",
      "ssm:GetCommandInvocation",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "EmptyQueues"
    actions   = ["sqs:GetQueueAttributes", "sqs:PurgeQueue"]
    resources = ["arn:aws:sqs:${local.region}:${local.account_id}:${var.name_prefix}-*"]
  }

  statement {
    sid       = "EmptyTables"
    actions   = ["dynamodb:DescribeTable", "dynamodb:Scan", "dynamodb:BatchWriteItem"]
    resources = ["arn:aws:dynamodb:${local.region}:${local.account_id}:table/${var.name_prefix}-*"]
  }

  statement {
    sid       = "ListStorageBucket"
    actions   = ["s3:ListBucket"]
    resources = [var.storage_bucket_arn]
  }

  statement {
    sid       = "EmptyStorageBucket"
    actions   = ["s3:DeleteObject"]
    resources = ["${var.storage_bucket_arn}/*"]
  }

  statement {
    sid       = "DeleteUsers"
    actions   = ["cognito-idp:ListUsers", "cognito-idp:AdminDeleteUser"]
    resources = [var.user_pool_arn]
  }

  # The same permissions as the start/stop workflows use for services: scale to 0 and back.
  statement {
    sid     = "EcsListServices"
    actions = ["ecs:ListServices"]
    resources = [
      "arn:aws:ecs:${local.region}:${local.account_id}:cluster/${var.ecs_cluster_name}",
      "arn:aws:ecs:${local.region}:${local.account_id}:service/${var.ecs_cluster_name}/*",
    ]
  }

  statement {
    sid       = "EcsScaleServices"
    actions   = ["ecs:DescribeServices", "ecs:UpdateService"]
    resources = ["arn:aws:ecs:${local.region}:${local.account_id}:service/${var.ecs_cluster_name}/*"]
  }

  # The database is emptied by a script that runs on the database access host (finops:switch = true).
  statement {
    sid       = "RunScript"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${local.region}::document/AWS-RunShellScript"]
  }

  statement {
    sid       = "RunScriptOnTheAccessHost"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ec2:${local.region}:${local.account_id}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/finops:switch"
      values   = ["true"]
    }
  }

  # Address and user name only: the password is read by the host itself and never reaches the workflow.
  statement {
    sid       = "ReadDatabaseAddress"
    actions   = ["ssm:GetParameter"]
    resources = var.database_parameter_arns
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "environment-reset"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.permissions.json
}

output "role_arn" {
  description = "Value for the AWS_RESET_ROLE_ARN variable in the GitHub environment."
  value       = aws_iam_role.this.arn
}
