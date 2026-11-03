# The public entry point: one HTTP API in front of all services and functions.
#
#   client --> API Gateway --> VPC link --> Cloud Map --> ECS task of the matching service
#   device --> API Gateway --> Lambda event-ingest --> SNS (events.tf)
#
# Every route is listed here, so this file shows the whole public surface, and every route
# names the authorizer that protects it. Add a route for every new path a service exposes.
# Who the callers are and what each may do: docs/identity-and-access.md.

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

  jwt_issuer = module.user_pool.issuer

  # Who may call: tokens of the web application, of the devices, or of both. The reserved name "iam"
  # (used by routes below, not listed here) means: an AWS Signature V4 request of an administrator.
  authorizers = {
    users             = [module.user_pool.client_ids["web"]]
    devices           = [module.user_pool.client_ids["device"]]
    users_and_devices = [module.user_pool.client_ids["web"], module.user_pool.client_ids["device"]]
  }

  services = {
    operations = {
      discovery_service_arn = module.operations_service.discovery_service_arn
      authorizer            = "users"

      # Mirrors the paths in operations-api.yaml; {proxy+} matches any sub-path.
      # Alerts are managed by people only.
      routes = [
        "ANY /api/v1/detections/{proxy+}",
        "POST /api/v1/alerts",
        "ANY /api/v1/alerts/{proxy+}",
      ]
    }

    # The alert list is read by the web application and by the devices (every device of an account
    # gets the alerts of its owner).
    operations_alert_list = {
      discovery_service_arn = module.operations_service.discovery_service_arn
      authorizer            = "users_and_devices"

      routes = ["GET /api/v1/alerts"]
    }

    # device-management-api.yaml. The device is never in the path: a device acts on itself, a person on
    # the device of their account. Routes are split by caller, so a token of the wrong kind is refused
    # here already (the service checks the caller type again).
    device_management = {
      discovery_service_arn = module.device_management_service.discovery_service_arn
      authorizer            = "users_and_devices"

      routes = [
        "GET /api/v1/device",
        "GET /api/v1/device/config",
      ]
    }

    # The owner edits the configuration (View 4) and charts the metrics (View 5).
    device_management_users = {
      discovery_service_arn = module.device_management_service.discovery_service_arn
      authorizer            = "users"

      routes = [
        "PUT /api/v1/device/config",
        "GET /api/v1/device/metrics",
      ]
    }

    # The device reports its metrics and asks for upload URLs of its photos.
    device_management_devices = {
      discovery_service_arn = module.device_management_service.discovery_service_arn
      authorizer            = "devices"

      routes = [
        "POST /api/v1/device/metrics",
        "POST /api/v1/images/presigned-urls",
      ]
    }

    # Creating and deleting devices. Only an administrator with AWS credentials may call it: requests
    # must be signed (SigV4) by a principal allowed to execute-api:Invoke on this API.
    device_management_admin = {
      discovery_service_arn = module.device_management_service.discovery_service_arn
      authorizer            = "iam"

      routes = [
        "POST /api/v1/admin/devices",
        "DELETE /api/v1/admin/devices/{deviceId}",
      ]
    }
  }

  functions = {
    event_ingest = {
      function_name = module.event_ingest.function_name
      invoke_arn    = module.event_ingest.invoke_arn
      authorizer    = "devices"

      # POST /api/v1/ingest/detections and /device-locations (defined in events.tf).
      routes = keys(local.ingest_routes)
    }
  }
}
