# Public HTTP API (API Gateway v2) in front of the platform. Two kinds of backends:
#
#   services:   internet --> HTTP API --> VPC link --> Cloud Map lookup --> task private IP:port
#   functions:  internet --> HTTP API --> Lambda function

variable "name" {
  type = string
}

variable "subnet_ids" {
  description = "Subnets for the VPC link's network interfaces."
  type        = list(string)
}

variable "vpc_link_security_group_id" {
  type = string
}

variable "services" {
  description = <<-EOT
    ECS services behind the API, keyed by a short name. Each entry names the Cloud Map
    service to forward to and the route keys sent there, e.g. "ANY /api/v1/alerts"
    or "ANY /api/v1/alerts/{proxy+}". When routes overlap, the most specific wins.
  EOT
  type = map(object({
    discovery_service_arn = string
    routes                = list(string)
  }))
}

variable "functions" {
  description = "Lambda functions behind the API, keyed by a short name: the function and the route keys it serves."
  type = map(object({
    function_name = string
    invoke_arn    = string
    routes        = list(string)
  }))
  default = {}
}

variable "account_id_header_value" {
  description = "TEMPORARY, until Cognito: every request is forced to act as this account (header X-Account-Id). Later replaced by the JWT 'sub' claim."
  type        = string
}

variable "cors_allowed_origins" {
  description = "Browser origins allowed to call the API (frontend dev server)."
  type        = list(string)
  default     = ["http://localhost:4200"]
}

variable "throttling_rate_limit" {
  description = "Steady requests per second for the whole API; caps the cost of abuse while the API is unauthenticated."
  type        = number
  default     = 20
}

variable "throttling_burst_limit" {
  type    = number
  default = 40
}

variable "log_retention_days" {
  type    = number
  default = 14
}

locals {
  # Flatten {backend => routes[]} into one map entry per route, so that each route can be
  # created with for_each. The key "<backend>|<route>" is stable across applies.
  service_routes = merge([
    for svc, cfg in var.services : {
      for route in cfg.routes : "${svc}|${route}" => { service = svc, route_key = route }
    }
  ]...)

  function_routes = merge([
    for fn, cfg in var.functions : {
      for route in cfg.routes : "${fn}|${route}" => { function = fn, route_key = route }
    }
  ]...)
}

resource "aws_apigatewayv2_api" "this" {
  name          = var.name
  protocol_type = "HTTP" # cheaper and simpler than REST API; no WAF or IP allowlist

  # API Gateway answers CORS preflight (OPTIONS) itself, so the backend does not have to.
  cors_configuration {
    allow_origins  = var.cors_allowed_origins
    allow_methods  = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers  = ["content-type", "authorization", "if-none-match", "x-trace-id"]
    expose_headers = ["etag", "x-trace-id"]
    max_age        = 3600
  }
}

# ---------------------------------------------------------------- services (ECS)

# The tunnel from API Gateway into the VPC. It is immutable (changing subnets or
# security groups replaces it) and goes INACTIVE after 60 days without traffic;
# the next request then waits a few minutes while AWS recreates its interfaces.
resource "aws_apigatewayv2_vpc_link" "this" {
  name               = var.name
  subnet_ids         = var.subnet_ids
  security_group_ids = [var.vpc_link_security_group_id]
}

# How requests reach a service: proxied as-is through the VPC link to whatever
# Cloud Map currently lists as healthy for that service.
resource "aws_apigatewayv2_integration" "service" {
  for_each = var.services

  api_id             = aws_apigatewayv2_api.this.id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.this.id
  integration_uri    = each.value.discovery_service_arn

  payload_format_version = "1.0"

  request_parameters = {
    # "overwrite": a client-supplied X-Account-Id is discarded, so callers cannot
    # impersonate another account.
    "overwrite:header.X-Account-Id" = var.account_id_header_value
  }
}

# One route per entry in `services`. Only listed paths are exposed; anything else gets 404.
resource "aws_apigatewayv2_route" "service" {
  for_each = local.service_routes

  api_id    = aws_apigatewayv2_api.this.id
  route_key = each.value.route_key
  target    = "integrations/${aws_apigatewayv2_integration.service[each.value.service].id}"
}

# The service routes used to be called "this"; the rename must not recreate them.
moved {
  from = aws_apigatewayv2_route.this
  to   = aws_apigatewayv2_route.service
}

# ---------------------------------------------------------------- functions (Lambda)

# Payload format 2.0: the function receives routeKey, lower-cased headers and the body,
# and returns {statusCode, headers, body}.
resource "aws_apigatewayv2_integration" "function" {
  for_each = var.functions

  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST" # Lambda is always invoked with POST, whatever the client's method
  integration_uri        = each.value.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "function" {
  for_each = local.function_routes

  api_id    = aws_apigatewayv2_api.this.id
  route_key = each.value.route_key
  target    = "integrations/${aws_apigatewayv2_integration.function[each.value.function].id}"
}

# A function may be invoked by this API only (any stage, any of its routes).
resource "aws_lambda_permission" "api" {
  for_each = var.functions

  statement_id  = "AllowInvokeFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = each.value.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

# ---------------------------------------------------------------- stage and access logs

resource "aws_cloudwatch_log_group" "access" {
  name              = "/apigateway/${var.name}"
  retention_in_days = var.log_retention_days
}

# The special "$default" stage serves from the root URL, with no /stage prefix in
# the public URL or in the path forwarded to the backend.
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true # route changes go live immediately

  default_route_settings {
    throttling_rate_limit  = var.throttling_rate_limit
    throttling_burst_limit = var.throttling_burst_limit
  }

  # One JSON line per request, handy for debugging integration errors.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      method           = "$context.httpMethod"
      path             = "$context.path"
      status           = "$context.status"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
      integrationMs    = "$context.integrationLatency"
    })
  }
}

output "api_endpoint" {
  description = "Public base URL of the API."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "api_id" {
  value = aws_apigatewayv2_api.this.id
}
