# Compute layer of the dev environment: cluster, services and the public API in front of them.
#
#   client --> API Gateway --> VPC link --> Cloud Map --> ECS task (operations-service)

variable "dev_account_id" {
  description = "TEMPORARY until Cognito: the account every API request acts as (value of the X-Account-Id header)."
  type        = string
  default     = "00000000-0000-0000-0000-000000000001"
}

module "cluster" {
  source = "../../modules/ecs-cluster"

  name   = local.name
  vpc_id = module.network.vpc_id
}

# Security group of the API Gateway VPC link. Service tasks accept traffic from
# this group only, so the VPC link is the single way in.
resource "aws_security_group" "vpc_link" {
  name        = "${local.name}-vpc-link"
  description = "API Gateway VPC link: may reach tasks inside the VPC"
  vpc_id      = module.network.vpc_id

  tags = {
    Name = "${local.name}-vpc-link-sg"
  }
}

resource "aws_vpc_security_group_egress_rule" "vpc_link_to_vpc" {
  security_group_id = aws_security_group.vpc_link.id
  description       = "To tasks inside the VPC"
  ip_protocol       = "-1"
  cidr_ipv4         = module.network.vpc_cidr
}

module "operations_ecr" {
  source = "../../modules/ecr"

  name = "anpr/operations-service"
}

module "operations_service" {
  source = "../../modules/ecs-service"

  name         = "${local.name}-operations-service"
  cluster_arn  = module.cluster.cluster_arn
  namespace_id = module.cluster.namespace_id
  vpc_id       = module.network.vpc_id
  subnet_ids   = module.network.public_subnet_ids

  ingress_security_group_id = aws_security_group.vpc_link.id

  image_repository_url = module.operations_ecr.repository_url

  # Zero tasks until the first image exists in ECR; the pipeline scales it up on first deploy.
  desired_count = 0
}

# The public entry point. Add a route here for every new path a service exposes.
module "api" {
  source = "../../modules/api-gateway"

  name                       = local.name
  subnet_ids                 = module.network.public_subnet_ids
  vpc_link_security_group_id = aws_security_group.vpc_link.id

  account_id_header_value = var.dev_account_id

  services = {
    operations = {
      discovery_service_arn = module.operations_service.discovery_service_arn

      # Mirrors the paths in operations-api.yaml; {proxy+} matches any sub-path.
      routes = [
        "ANY /api/v1/views/{proxy+}",
        "ANY /api/v1/alerts",
        "ANY /api/v1/alerts/{proxy+}",
        "ANY /api/v1/devices/{deviceId}/alerts",
      ]
    }
  }
}
