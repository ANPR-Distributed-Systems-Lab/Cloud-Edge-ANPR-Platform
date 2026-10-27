# Lets GitHub Actions work in this environment without stored AWS credentials (OpenID Connect).
#
# This file holds what is shared by all workflows: the trust in GitHub and the role of the
# start/stop workflows. The deploy role of each service lives in that service's own file.

# Registers GitHub as a trusted identity provider. One per AWS account and URL,
# shared by every role that GitHub workflows assume.
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
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
  github_environment   = var.environment # the GitHub environment is named like the Terraform one

  ecs_cluster_name = module.cluster.cluster_name
  rds_name_prefix  = local.name
}
