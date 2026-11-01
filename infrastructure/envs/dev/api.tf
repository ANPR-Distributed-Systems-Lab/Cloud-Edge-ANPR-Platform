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

      # Mirrors the paths in operations-api.yaml (except the alert list of a device, see below);
      # {proxy+} matches any sub-path. Alerts are managed by people only.
      routes = [
        "ANY /api/v1/views/{proxy+}",
        "POST /api/v1/alerts",
        "ANY /api/v1/alerts/{proxy+}",
      ]
    }

    # The alert list is read by the web application and by the devices (every device of an account
    # gets the alerts of its owner), so it replaces GET /api/v1/devices/{deviceId}/alerts.
    operations_alert_list = {
      discovery_service_arn = module.operations_service.discovery_service_arn
      authorizer            = "users_and_devices"

      routes = ["GET /api/v1/alerts"]
    }

    device_management = {
      discovery_service_arn = module.device_management_service.discovery_service_arn
      authorizer            = "users_and_devices" # devices fetch their configuration, the web application shows it

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

    # Pairing of devices with accounts (creates the Cognito user of the device and publishes
    # device.paired). Only an administrator with AWS credentials may call it: requests must be
    # signed (SigV4) by a principal allowed to execute-api:Invoke on this API. The contract is
    # still to be written, so the whole /admin namespace is routed.
    device_management_admin = {
      discovery_service_arn = module.device_management_service.discovery_service_arn
      authorizer            = "iam"

      routes = ["ANY /api/v1/admin/{proxy+}"]
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
