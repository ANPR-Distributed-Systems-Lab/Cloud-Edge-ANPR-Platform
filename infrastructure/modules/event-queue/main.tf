# The SQS queue of one consuming service, subscribed to an SNS topic (fan-out), with a
# dead-letter queue for messages the consumer keeps failing on.
#
#   SNS topic --(raw delivery)--> queue --(after max_receive_count failures)--> DLQ
#
# Consumers use plain SQS: ReceiveMessage (long polling), process, DeleteMessage.

variable "name" {
  description = "Queue name, e.g. anpr-dev-operations-events. The DLQ gets the suffix -dlq."
  type        = string
}

variable "topic_arn" {
  description = "SNS topic the queue subscribes to."
  type        = string
}

variable "filter_policy" {
  description = "Optional SNS filter policy (JSON) on message attributes, e.g. to receive one eventType only. Null = every message."
  type        = string
  default     = null
}

variable "visibility_timeout_seconds" {
  description = "How long a received message stays hidden from other consumers; must exceed the processing time of one message."
  type        = number
  default     = 60
}

variable "max_receive_count" {
  description = "Deliveries without a DeleteMessage before the message moves to the DLQ."
  type        = number
  default     = 5
}

variable "message_retention_seconds" {
  type    = number
  default = 345600 # 4 days
}

variable "dlq_message_retention_seconds" {
  description = "Longer than the queue, so failed messages can still be inspected and redriven."
  type        = number
  default     = 1209600 # 14 days, the SQS maximum
}

# ---------------------------------------------------------------- queues

resource "aws_sqs_queue" "dlq" {
  name                      = "${var.name}-dlq"
  message_retention_seconds = var.dlq_message_retention_seconds
  sqs_managed_sse_enabled   = true # encrypted at rest with SQS-owned keys (no KMS cost)
}

resource "aws_sqs_queue" "this" {
  name                       = var.name
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = 20 # long polling by default: fewer empty receives, lower cost
  sqs_managed_sse_enabled    = true

  # A message that keeps failing goes to the DLQ instead of blocking the queue.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

# Only this queue may use the DLQ as its dead-letter target.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.this.arn]
  })
}

# ---------------------------------------------------------------- subscription

# SNS may deliver to the queue only on behalf of this topic. Requests without TLS are refused.
data "aws_iam_policy_document" "queue" {
  statement {
    sid       = "AllowTopicToSend"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.this.arn]

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [var.topic_arn]
    }
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["sqs:*"]
    resources = [aws_sqs_queue.this.arn]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_sqs_queue_policy" "this" {
  queue_url = aws_sqs_queue.this.id
  policy    = data.aws_iam_policy_document.queue.json
}

# Raw delivery: the SQS body is exactly the published message (no SNS JSON envelope), and
# SNS message attributes arrive as SQS message attributes (at most 10).
resource "aws_sns_topic_subscription" "this" {
  topic_arn            = var.topic_arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.this.arn
  raw_message_delivery = true
  filter_policy        = var.filter_policy

  # Without the queue policy SNS cannot deliver, and messages published meanwhile are lost.
  depends_on = [aws_sqs_queue_policy.this]
}

output "queue_url" {
  description = "What consumers pass to ReceiveMessage / DeleteMessage."
  value       = aws_sqs_queue.this.id
}

output "queue_arn" {
  value = aws_sqs_queue.this.arn
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.id
}

output "dlq_arn" {
  value = aws_sqs_queue.dlq.arn
}
