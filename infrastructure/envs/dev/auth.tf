# Authentication: Amazon Cognito issues the tokens, API Gateway validates them (api.tf).
#
#   web client      people using the web application
#   device client   Raspberry Pi edge nodes; each device is a user of the pool
#
# Every user belongs to one account (attribute custom:account_id). API Gateway hands the
# identity to the backends: services receive the headers X-Account-Id and X-User-Id, and the
# ingest function receives the claims (see api.tf and events.tf).
#
# Users are created by administrators, for example:
#   aws cognito-idp admin-create-user --user-pool-id <id> --username <name> --message-action SUPPRESS \
#       --user-attributes Name=custom:account_id,Value=<account uuid>
#   aws cognito-idp admin-set-user-password --user-pool-id <id> --username <name> --password <...> --permanent

# Source: infrastructure/lambdas/token_claims/token_claims.py (unit tests next to it).
module "token_claims" {
  source = "../../modules/lambda-function"

  name            = "${local.name}-token-claims"
  source_file     = "${path.module}/../../lambdas/token_claims/token_claims.py"
  handler         = "token_claims.handler"
  timeout_seconds = 5 # Cognito gives a trigger 5 seconds
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

  pre_token_function_name = module.token_claims.function_name
  pre_token_function_arn  = module.token_claims.function_arn
}
