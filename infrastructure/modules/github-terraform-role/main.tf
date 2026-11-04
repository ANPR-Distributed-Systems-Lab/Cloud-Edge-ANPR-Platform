# IAM role that the "Deploy infrastructure" workflow assumes (via OpenID Connect) to run
# terraform plan and apply.
#
# Terraform creates IAM roles, networks and databases, so this role is an administrator of the
# account. What protects it is who can assume it: one repository and one GitHub environment,
# which is meant to be used by the infrastructure workflow only and to accept only trusted
# branches (configured in GitHub: Settings -> Environments).

variable "name" {
  description = "Role name, e.g. anpr-dev-terraform."
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

locals {
  github_owner = split("/", var.github_repository)[0]
  github_name  = split("/", var.github_repository)[1]

  # Same subject format as the other GitHub roles: immutable numeric ids included.
  oidc_subject = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_name}@${var.github_repository_id}:environment:${var.github_environment}"
}

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

resource "aws_iam_role_policy_attachment" "administrator" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

output "role_arn" {
  description = "Value for the AWS_TERRAFORM_ROLE_ARN variable in the GitHub environment."
  value       = aws_iam_role.this.arn
}
