# A Python Lambda function deployed from a single source file, with its own role,
# log group (bounded retention) and structured JSON logs.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
    archive = {
      source = "hashicorp/archive"
    }
  }
}

variable "name" {
  description = "Function name, also used for its role and log group, e.g. anpr-dev-event-ingest."
  type        = string
}

variable "source_file" {
  description = "Path to the single .py file that holds the handler."
  type        = string
}

variable "handler" {
  description = "<module>.<function>, e.g. handler.handler."
  type        = string
}

variable "runtime" {
  type    = string
  default = "python3.14"
}

variable "memory_mb" {
  type    = number
  default = 128
}

variable "timeout_seconds" {
  type    = number
  default = 10
}

variable "environment" {
  description = "Environment variables of the function."
  type        = map(string)
  default     = {}
}

variable "policies" {
  description = "Policy name -> IAM policy JSON: what the function may do besides writing its logs."
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  type    = number
  default = 14
}

# ---------------------------------------------------------------- code

# Zipped on every plan; the hash below makes Terraform update the function only when
# the source file changes. The .build/ folder is gitignored.
data "archive_file" "code" {
  type        = "zip"
  source_file = var.source_file
  output_path = "${path.root}/.build/${var.name}.zip"
}

# ---------------------------------------------------------------- logs

# Created before the function, so Lambda does not create it without a retention.
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------- IAM

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.name
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Write logs to its own log group only (the AWS managed basic execution policy would
# allow creating any log group in the account).
data "aws_iam_policy_document" "logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.this.arn}:*"]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "write-logs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logs.json
}

resource "aws_iam_role_policy" "extra" {
  for_each = var.policies

  name   = each.key
  role   = aws_iam_role.this.id
  policy = each.value
}

# ---------------------------------------------------------------- function

resource "aws_lambda_function" "this" {
  function_name = var.name
  role          = aws_iam_role.this.arn
  runtime       = var.runtime
  architectures = ["arm64"] # Graviton: cheaper than x86, and pure Python needs no rebuild
  handler       = var.handler
  memory_size   = var.memory_mb
  timeout       = var.timeout_seconds

  filename         = data.archive_file.code.output_path
  source_code_hash = data.archive_file.code.output_base64sha256

  environment {
    variables = var.environment
  }

  # Records of the Python logging module become JSON objects in CloudWatch (CLAUDE.md:
  # structured logs only); the level is set here, not in code.
  logging_config {
    log_format            = "JSON"
    log_group             = aws_cloudwatch_log_group.this.name
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  depends_on = [aws_iam_role_policy.logs]
}

output "function_name" {
  value = aws_lambda_function.this.function_name
}

output "function_arn" {
  value = aws_lambda_function.this.arn
}

output "invoke_arn" {
  description = "Used by API Gateway integrations."
  value       = aws_lambda_function.this.invoke_arn
}

output "role_name" {
  value = aws_iam_role.this.name
}
