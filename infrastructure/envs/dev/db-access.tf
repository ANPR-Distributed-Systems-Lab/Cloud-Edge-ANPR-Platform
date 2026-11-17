# Administrator access to the private databases, through AWS Systems Manager (no SSH, no open port).
#
#   laptop --aws ssm start-session (port forwarding)--> access host --> database
#
# Used by pgAdmin on a laptop (scripts/environment/db_tunnel.py) and by the reset of the environment. Every
# database lists the host's security group as an allowed client (see operations-service.tf). The
# environment start/stop workflows switch the host on and off with the databases.

module "db_access_host" {
  source = "../../modules/db-access-host"

  name      = "${local.name}-db-access"
  vpc_id    = module.network.vpc_id
  vpc_cidr  = module.network.vpc_cidr
  subnet_id = module.network.public_subnet_ids[0]

  # The reset of the environment runs psql here and needs the password of the database.
  readable_parameter_arns = [module.operations_rds.ssm_parameter_arns["SPRING_DATASOURCE_PASSWORD"]]
}
