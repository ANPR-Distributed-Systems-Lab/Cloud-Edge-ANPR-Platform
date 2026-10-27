# The user directory of the platform: web users and edge devices sign in here, and API Gateway
# validates the access tokens issued by this pool.
#
# Nobody can sign up on their own. Administrators (later device-management-service, for devices)
# create the users and give each one the account it belongs to.

variable "name" {
  type = string
}

variable "clients" {
  description = "App clients by name; the value lists the sign-in flows the client may use (ALLOW_*)."
  type        = map(list(string))
}

variable "pre_token_function_name" {
  description = "Lambda that copies the account of the user into a claim (see lambdas/token_claims)."
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

  # The account (tenant) of the user, stored as custom:account_id. Immutable on purpose: it is
  # set when an administrator creates the user, and no client can change it later.
  schema {
    name                = "account_id"
    attribute_data_type = "String"
    mutable             = false
    required            = false

    string_attribute_constraints {
      min_length = 36 # a UUID
      max_length = 36
    }
  }

  lambda_config {
    pre_token_generation_config {
      lambda_arn     = var.pre_token_function_arn
      lambda_version = "V2_0"
    }
  }
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

output "client_ids" {
  description = "App client id by client name; also the `client_id` claim of its access tokens."
  value       = { for name, client in aws_cognito_user_pool_client.this : name => client.id }
}
