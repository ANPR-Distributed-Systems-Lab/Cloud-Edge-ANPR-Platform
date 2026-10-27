# The ECS cluster all services run in, and the Cloud Map namespace they register in.

module "cluster" {
  source = "../../modules/ecs-cluster"

  name   = local.name
  vpc_id = module.network.vpc_id
}
