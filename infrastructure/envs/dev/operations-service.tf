# operations-service: everything the service owns, in one place.
# Image repository, database, ECS service and the role its deploy workflow uses.
# Its API routes are registered in api.tf.

# ---------------------------------------------------------------- image repository

module "operations_ecr" {
  source = "../../modules/ecr"

  name = "anpr/operations-service"
}

# ---------------------------------------------------------------- database
# Private: reachable only from the service's tasks.
# Developers work against a local PostgreSQL (docker-compose); this one serves the deployed environment.

module "operations_rds" {
  source = "../../modules/rds"

  name       = "${local.name}-operations"
  vpc_id     = module.network.vpc_id
  subnet_ids = module.network.private_subnet_ids

  allowed_security_group_ids = [module.operations_service.task_security_group_id]

  ssm_prefix      = "/anpr/${var.environment}/operations-service"
  database_name   = "operations"
  master_username = "operations_admin"
}

# ---------------------------------------------------------------- service

module "operations_service" {
  source = "../../modules/ecs-service"

  name         = "${local.name}-operations-service"
  cluster_arn  = module.cluster.cluster_arn
  namespace_id = module.cluster.namespace_id
  vpc_id       = module.network.vpc_id
  subnet_ids   = module.network.public_subnet_ids

  ingress_security_group_id = aws_security_group.vpc_link.id

  image_repository_url = module.operations_ecr.repository_url

  # Database connection settings, injected as SPRING_DATASOURCE_* environment variables.
  secrets = module.operations_rds.ssm_parameter_arns

  # Zero tasks until the first image exists in ECR; the pipeline scales it up on first deploy.
  desired_count = 0

  # Tasks the "start environment" workflow runs for this service (0 = never started automatically).
  start_count = 1
}

# ---------------------------------------------------------------- deploy role
# What the deploy workflow of this service may do: push to its repository and update its
# service, nothing else.

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
