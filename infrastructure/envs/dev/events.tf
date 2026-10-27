# Events sent by the edge devices (Raspberry Pi) and their fan-out to the services.
#
#   RPi --POST /api/v1/ingest/...--> API Gateway --> Lambda event-ingest --> SNS topic --> SQS queue per
#   (device token, see auth.tf)       (validates the token)                                  consuming service
#
# Every message on the topic is:
#   body        the JSON the device sent, unchanged
#   attributes  eventType   detection | device-location (from the route; subscriptions can filter on it)
#               traceId     end-to-end trace id (CLAUDE.md: passed through APIs and queues)
#               accountId   account of the device, from its token
#               deviceId    the device, from its token
#
# Consumers subscribe with the event-queue module, next to the rest of their service
# (see operations-service.tf).

locals {
  # Ingest route -> event type. The single source of truth: API Gateway registers these
  # routes (api.tf) and the Lambda receives the mapping to set eventType.
  ingest_routes = {
    "POST /api/v1/ingest/detections"       = "detection"
    "POST /api/v1/ingest/device-locations" = "device-location"
  }
}

# ---------------------------------------------------------------- topic

# The AWS managed key of SNS. Reading it also creates it in an account that has never used
# it (KMS creates AWS managed keys on first use), so the ARN below is always available.
data "aws_kms_key" "sns" {
  key_id = "alias/aws/sns"
}

resource "aws_sns_topic" "edge_events" {
  name              = "${local.name}-edge-events"
  kms_master_key_id = "alias/aws/sns" # encrypted at rest: messages contain plates and GPS positions
}

# Publishers and subscribers get access through IAM; the topic policy only refuses
# publishing without TLS.
data "aws_iam_policy_document" "edge_events_topic" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.edge_events.arn]

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

resource "aws_sns_topic_policy" "edge_events" {
  arn    = aws_sns_topic.edge_events.arn
  policy = data.aws_iam_policy_document.edge_events_topic.json
}

# ---------------------------------------------------------------- ingest function

data "aws_iam_policy_document" "publish_edge_events" {
  statement {
    sid       = "PublishToTopic"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.edge_events.arn]
  }

  # The topic is encrypted, so publishing also needs the topic's key.
  statement {
    sid       = "UseTopicKey"
    actions   = ["kms:GenerateDataKey*", "kms:Decrypt"]
    resources = [data.aws_kms_key.sns.arn]
  }
}

# Source: infrastructure/lambdas/event_ingest/handler.py (unit tests next to it).
module "event_ingest" {
  source = "../../modules/lambda-function"

  name        = "${local.name}-event-ingest"
  source_file = "${path.module}/../../lambdas/event_ingest/handler.py"
  handler     = "handler.handler"

  environment = {
    TOPIC_ARN           = aws_sns_topic.edge_events.arn
    EVENT_TYPE_BY_ROUTE = jsonencode(local.ingest_routes)
  }

  policies = {
    publish-edge-events = data.aws_iam_policy_document.publish_edge_events.json
  }
}
