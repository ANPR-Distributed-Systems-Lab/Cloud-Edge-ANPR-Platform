# Input variables of the dev environment. Every default is the value used in dev.

variable "region" {
  description = "AWS region of the environment."
  type        = string
  default     = "eu-central-1"
}

variable "environment" {
  description = "Environment name; part of every resource name and of the GitHub environment name."
  type        = string
  default     = "dev"
}

variable "dev_account_id" {
  description = "TEMPORARY until Cognito: the account every API request acts as (value of the X-Account-Id header)."
  type        = string
  default     = "00000000-0000-0000-0000-000000000001"
}

# ---------------------------------------------------------------- GitHub (OIDC trust)

variable "github_repository" {
  description = "Repository whose workflows may deploy, as owner/name."
  type        = string
  default     = "ANPR-Distributed-Systems-Lab/Cloud-Edge-ANPR-Platform"
}

# Immutable GitHub ids, as they appear in the OIDC token's "sub" claim
# (see GET https://api.github.com/repos/<owner>/<repo>, or decode a workflow's OIDC token).
variable "github_owner_id" {
  description = "Numeric GitHub id of the repository owner."
  type        = string
  default     = "322300658"
}

variable "github_repository_id" {
  description = "Numeric GitHub id of the repository."
  type        = string
  default     = "1350589930"
}
