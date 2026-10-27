# One DynamoDB table with the platform defaults: on-demand capacity, point-in-time
# recovery and deletion protection. Only key attributes are declared here; DynamoDB
# is schemaless for every other attribute.

variable "name" {
  type = string
}

variable "hash_key" {
  description = "Partition key attribute name."
  type        = string
}

variable "hash_key_type" {
  description = "S (string), N (number) or B (binary)."
  type        = string
  default     = "S"
}

variable "range_key" {
  description = "Optional sort key attribute name."
  type        = string
  default     = null
}

variable "range_key_type" {
  type    = string
  default = "S"
}

variable "ttl_attribute" {
  description = "Optional attribute holding an expiry time in epoch seconds; DynamoDB deletes expired items for free."
  type        = string
  default     = null
}

variable "deletion_protection" {
  type    = bool
  default = true
}

resource "aws_dynamodb_table" "this" {
  name         = var.name
  billing_mode = "PAY_PER_REQUEST" # pay per request, nothing while idle
  hash_key     = var.hash_key
  range_key    = var.range_key

  attribute {
    name = var.hash_key
    type = var.hash_key_type
  }

  dynamic "attribute" {
    for_each = var.range_key == null ? [] : [var.range_key]

    content {
      name = attribute.value
      type = var.range_key_type
    }
  }

  dynamic "ttl" {
    for_each = var.ttl_attribute == null ? [] : [var.ttl_attribute]

    content {
      attribute_name = ttl.value
      enabled        = true
    }
  }

  # Restore to any second of the last 35 days.
  point_in_time_recovery {
    enabled = true
  }

  deletion_protection_enabled = var.deletion_protection

  # Encrypted at rest by default with an AWS owned key (no KMS cost), so no block is needed.
}

output "name" {
  value = aws_dynamodb_table.this.name
}

output "arn" {
  value = aws_dynamodb_table.this.arn
}
