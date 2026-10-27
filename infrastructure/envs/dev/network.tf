# Network shared by every service: public subnets for the tasks, private ones for databases.

module "network" {
  source = "../../modules/network"

  name = local.name
}
