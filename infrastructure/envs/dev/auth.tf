# Authentication: Amazon Cognito issues the tokens, API Gateway validates them (api.tf).
# The model is described in docs/identity-and-access.md.
#
#   web client      people using the web application
#   device client   Raspberry Pi edge nodes; each device is a user of the pool
#
# What a user is, a person or a device, is the group it belongs to. A pre token generation trigger turns
# the group into the claim account_type ("user" or "device"). API Gateway hands the identity to the
# backends: services receive the headers X-Account-Id (sub of the token) and X-Account-Type, the ingest
# function receives the claims (see api.tf and events.tf). The account that owns a device is not in the
# token: services learn it from the device-events topic (device-events.tf).
#
# People are created by administrators with infrastructure/scripts/create_user.py (group "users").
# Devices are created by device-management-service when an administrator creates them (group "devices").

locals {
  # Group of the user pool -> account_type claim of its tokens. The single source of truth: the user
  # pool creates the groups, the trigger receives the mapping.
  account_type_by_group = {
    users   = "user"
    devices = "device"
  }
}

# Source: infrastructure/lambdas/token_claims/token_claims.py (unit tests next to it).
module "token_claims" {
  source = "../../modules/lambda-function"

  name            = "${local.name}-token-claims"
  source_file     = "${path.module}/../../lambdas/token_claims/token_claims.py"
  handler         = "token_claims.handler"
  timeout_seconds = 5 # Cognito gives a trigger 5 seconds

  environment = {
    ACCOUNT_TYPE_BY_GROUP = jsonencode(local.account_type_by_group)
  }
}

module "user_pool" {
  source = "../../modules/cognito-user-pool"

  name = local.name

  clients = {
    # ADMIN_USER_PASSWORD_AUTH lets an administrator obtain a token from the CLI (testing).
    web = ["ALLOW_USER_SRP_AUTH", "ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]

    # Password sign-in over TLS: the simplest flow for a Python client on the device.
    device = ["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  }

  groups = keys(local.account_type_by_group)

  pre_token_function_name = module.token_claims.function_name
  pre_token_function_arn  = module.token_claims.function_arn
}
