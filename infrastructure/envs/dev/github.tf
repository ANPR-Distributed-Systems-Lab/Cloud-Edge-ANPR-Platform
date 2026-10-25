# Lets GitHub Actions deploy to this environment without stored AWS credentials.

variable "github_repository" {
  description = "Repository whose workflows may deploy, as owner/name."
  type        = string
  default     = "ANPR-Distributed-Systems-Lab/Cloud-Edge-ANPR-Platform"
}

# Immutable GitHub ids, as they appear in the OIDC token's "sub" claim
# (see the "Debug OIDC claims" step output, or GET https://api.github.com/repos/<owner>/<repo>).
variable "github_owner_id" {
  type    = string
  default = "322300658"
}

variable "github_repository_id" {
  type    = string
  default = "1350589930"
}

# Registers GitHub as a trusted identity provider. One per AWS account and URL,
# shared by every deploy role in the account.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

module "operations_deploy_role" {
  source = "../../modules/github-deploy-role"

  name                 = "${local.name}-operations-deploy"
  oidc_provider_arn    = aws_iam_openid_connect_provider.github.arn
  github_repository    = var.github_repository
  github_owner_id      = var.github_owner_id
  github_repository_id = var.github_repository_id
  github_environment   = var.environment # the GitHub environment is named like the Terraform one

  ecr_repository_arn = module.operations_ecr.repository_arn
  ecs_service_arn    = module.operations_service.service_arn
  pass_role_arns = [
    module.operations_service.execution_role_arn,
    module.operations_service.task_role_arn,
  ]
}

# Role of the "start environment" / "stop environment" workflows (FinOps): switches ECS
# services and RDS on and off. Scoped by naming convention, so new services and databases
# need no change here.
module "env_power_role" {
  source = "../../modules/github-power-role"

  name                 = "${local.name}-env-power"
  oidc_provider_arn    = aws_iam_openid_connect_provider.github.arn
  github_repository    = var.github_repository
  github_owner_id      = var.github_owner_id
  github_repository_id = var.github_repository_id
  github_environment   = var.environment

  ecs_cluster_name = module.cluster.cluster_name
  rds_name_prefix  = local.name
}
