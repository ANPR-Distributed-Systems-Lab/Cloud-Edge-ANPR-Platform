# The user directory of the platform: web users and edge devices sign in here, and API Gateway
# validates the access tokens issued by this pool.
#
# Nobody can sign up on their own. Administrators create the people, device-management-service
# creates the devices. Every user belongs to exactly one group, which tells what kind of account it
# is (a person or a device); a trigger turns the group into the claim account_type of the tokens.

variable "name" {
  type = string
}

variable "clients" {
  description = "App clients by name; the value lists the sign-in flows the client may use (ALLOW_*)."
  type        = map(list(string))
}

variable "groups" {
  description = "Names of the groups that tell the kind of account (e.g. users, devices); create each user in one of them."
  type        = set(string)
}

variable "pre_token_function_name" {
  description = "Lambda that turns the group of the user into the claim account_type (see lambdas/token_claims)."
  type        = string
}

variable "pre_token_function_arn" {
  type = string
}

resource "aws_cognito_user_pool" "this" {
  name = var.name

  # Essentials is required by version 2 of the pre token generation trigger (access token claims).
  user_pool_tier      = "ESSENTIALS"
  deletion_protection = "ACTIVE"
  mfa_configuration   = "OFF"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "admin_only"
      priority = 1
    }
  }

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }

  lambda_config {
    pre_token_generation_config {
      lambda_arn     = var.pre_token_function_arn
      lambda_version = "V2_0"
    }
  }
}

# Membership is assigned by administrators and services with the right IAM permissions only;
# no client can change it, so the claim account_type cannot be forged.
resource "aws_cognito_user_group" "this" {
  for_each = var.groups

  name         = each.key
  user_pool_id = aws_cognito_user_pool.this.id
}

resource "aws_lambda_permission" "pre_token" {
  statement_id  = "AllowInvokeFromCognito"
  action        = "lambda:InvokeFunction"
  function_name = var.pre_token_function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.this.arn
}

# Public clients (no secret): the secret of a client baked into a device or a browser would not be secret.
resource "aws_cognito_user_pool_client" "this" {
  for_each = var.clients

  name         = "${var.name}-${each.key}"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret               = false
  explicit_auth_flows           = each.value
  prevent_user_existence_errors = "ENABLED"
}

output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "issuer" {
  description = "The `iss` of the tokens, what API Gateway authorizers check."
  value       = "https://${aws_cognito_user_pool.this.endpoint}"
}

output "user_pool_arn" {
  description = "What IAM policies of services that manage users refer to."
  value       = aws_cognito_user_pool.this.arn
}

output "client_ids" {
  description = "App client id by client name; also the `client_id` claim of its access tokens."
  value       = { for name, client in aws_cognito_user_pool_client.this : name => client.id }
}
