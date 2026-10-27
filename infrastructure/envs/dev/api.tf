# The public entry point: one HTTP API in front of all services and functions.
#
#   client --> API Gateway --> VPC link --> Cloud Map --> ECS task of the matching service
#   device --> API Gateway --> Lambda event-ingest --> SNS (events.tf)
#
# Every route is listed here, so this file shows the whole public surface.
# Add a route for every new path a service exposes.

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

    device_management = {
      discovery_service_arn = module.device_management_service.discovery_service_arn

      # The paths of the architecture diagram; the contract itself is still being written
      # (device-management-api.yaml), until then the service answers 404 on all of them.
      # They do not overlap with the operations routes above: API Gateway picks the route
      # whose path matches most specifically.
      routes = [
        "ANY /api/v1/devices/{deviceId}/config",
        "ANY /api/v1/devices/{deviceId}/heartbeat",
        "ANY /api/v1/devices/{deviceId}/status",
        "ANY /api/v1/images/presigned-urls",
      ]
    }
  }

  functions = {
    event_ingest = {
      function_name = module.event_ingest.function_name
      invoke_arn    = module.event_ingest.invoke_arn

      # POST /api/v1/ingest/detections and /device-locations (defined in events.tf).
      routes = keys(local.ingest_routes)
    }
  }
}
