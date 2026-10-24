# Database of operations-service. Private: reachable only from the service's tasks.
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
