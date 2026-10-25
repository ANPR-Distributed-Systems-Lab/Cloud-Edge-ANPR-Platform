# device-management-service: everything the service owns, in one place.
# Image repository, ECS service and the role its deploy workflow uses.
# Its API routes are registered in api.tf.
#
# The DynamoDB tables and the task role's access to them are still to be added (a "database"
# section, as in operations-service.tf); for now the service only needs to run.

# ---------------------------------------------------------------- image repository

module "device_management_ecr" {
  source = "../../modules/ecr"

  name = "anpr/device-management-service"
}

# ---------------------------------------------------------------- service

module "device_management_service" {
  source = "../../modules/ecs-service"

  name         = "${local.name}-device-management-service"
  cluster_arn  = module.cluster.cluster_arn
  namespace_id = module.cluster.namespace_id
  vpc_id       = module.network.vpc_id
  subnet_ids   = module.network.public_subnet_ids

  ingress_security_group_id = aws_security_group.vpc_link.id

  image_repository_url = module.device_management_ecr.repository_url

  # Zero tasks until the first image exists in ECR; the pipeline deploys it, then the
  # "start environment" workflow (or a manual scale-up) switches it on.
  desired_count = 0

  # Tasks the "start environment" workflow runs for this service (0 = never started automatically).
  # Kept at 0 until the first image is in ECR: a task without an image never becomes healthy and
  # would make the start workflow wait and fail. Set it to 1 after the first deploy.
  start_count = 0
}

# ---------------------------------------------------------------- deploy role
# What the deploy workflow of this service may do: push to its repository and update its
# service, nothing else.

module "device_management_deploy_role" {
  source = "../../modules/github-deploy-role"

  name                 = "${local.name}-device-management-deploy"
  oidc_provider_arn    = aws_iam_openid_connect_provider.github.arn
  github_repository    = var.github_repository
  github_owner_id      = var.github_owner_id
  github_repository_id = var.github_repository_id
  github_environment   = var.environment

  ecr_repository_arn = module.device_management_ecr.repository_arn
  ecs_service_arn    = module.device_management_service.service_arn
  pass_role_arns = [
    module.device_management_service.execution_role_arn,
    module.device_management_service.task_role_arn,
  ]
}
